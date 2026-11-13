import datetime as dt
import io
import os

from PIL import Image, ImageDraw, ImageFont

from pc321_db import _connect
from tarif import SQL, TZ, band_for_hour, hourly_kwh, money

STOP_W = float(os.environ.get("COMP_STOP_W", "10000"))
V_MIN = float(os.environ.get("V_MIN", "198"))
V_MAX = float(os.environ.get("V_MAX", "242"))
OFFLINE_S = 120
MONTHS = ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul",
          "avgust", "sentabr", "oktabr", "noyabr", "dekabr"]
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FORMAT_MSG = "Format: /xulosa yoki /xulosa 2026-11-02 (yil-oy-kun)"


def d(x):
    x = int(x)
    h, m = x // 3600, (x % 3600) // 60
    if h:
        return f"{h} soat {m} daqiqa"
    return f"{m} daqiqa" if m else f"{x} soniya"


def cost(data, day=None):
    return sum(k * band_for_hour(h, day)[1] for h, k in data.items())


def parse_day(arg, today):
    if not arg:
        return today
    a = arg.strip().lower()
    try:
        return dt.date.fromisoformat(a)
    except ValueError:
        raise ValueError(FORMAT_MSG)


def data(day):
    now = dt.datetime.now(TZ)
    today = now.date()
    is_today = day == today
    day0 = dt.datetime.combine(day, dt.time.min, tzinfo=TZ)
    day1 = day0 + dt.timedelta(days=1)
    upto = now if is_today else day1

    with _connect().cursor() as cur:
        cur.execute("SELECT ts, p_total, v_a, v_b, v_c FROM readings "
                    "WHERE ts < %s ORDER BY ts DESC LIMIT 1", (upto,))
        last = cur.fetchone()
        if not last or last[0] < day0:
            return None
        cur.execute("""
            SELECT COALESCE(SUM(EXTRACT(EPOCH FROM (nt - ts))), 0) FROM (
                SELECT ts, p_total, LEAD(ts) OVER (ORDER BY ts) AS nt
                FROM readings WHERE ts >= %s AND ts < %s) t
            WHERE p_total < %s AND nt - ts <= interval '60 seconds'""", (day0, day1, STOP_W))
        stop = float(cur.fetchone()[0])
        cur.execute("""
            SELECT COALESCE(SUM(EXTRACT(EPOCH FROM (nt - ts))), 0) FROM (
                SELECT ts, LEAD(ts) OVER (ORDER BY ts) AS nt
                FROM readings WHERE ts >= %s AND ts < %s) t
            WHERE nt - ts <= interval '60 seconds'""", (day0, day1))
        covered = float(cur.fetchone()[0])
        cur.execute("SELECT COUNT(*) FROM events WHERE kind <> 'toxtash' "
                    "AND started_at >= %s AND started_at < %s", (day0, day1))
        n_ev = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM events WHERE kind = 'kuchlanish' "
                    "AND started_at >= %s AND started_at < %s", (day0, day1))
        n_volt = cur.fetchone()[0]
        cur.execute("SELECT AVG(p_total) FROM readings WHERE ts >= %s AND ts < %s", (day0, day1))
        avg_w = float(cur.fetchone()[0] or 0)
        cur.execute(SQL, (day0.replace(day=1), upto))
        month_rows = cur.fetchall()

    ts, p, *volts = last
    age = (now - ts).total_seconds()

    day_data = hourly_kwh(day)
    prev = hourly_kwh(day - dt.timedelta(days=1))
    pct = None
    hrs = [h for h in range(now.hour if is_today else 24) if h in day_data and h in prev]
    if hrs:
        t, y = sum(day_data[h] for h in hrs), sum(prev[h] for h in hrs)
        if y > 0:
            pct = (t - y) / y * 100

    if is_today:
        bad_v = any(v is not None and (v < V_MIN or v > V_MAX) for v in volts)
        offline = age > OFFLINE_S
    else:
        bad_v = n_volt > 0
        offline = False

    if offline:
        status, head, sub = "red", "MUAMMO", "hisoblagich bilan aloqa uzilgan"
    elif bad_v:
        status, head, sub = "red", "MUAMMO", "kuchlanish me'yordan chiqqan"
    elif pct is not None and pct > 30:
        status, head, sub = "yellow", "E'TIBOR", f"sarf oldingi kundan {pct:.0f}% ko'p"
    else:
        status, head, sub = "green", "HAMMASI JOYIDA", ""

    if is_today:
        title = f"{day.day}-{MONTHS[day.month - 1]}, {now:%H:%M}"
        p_label, p_val = "HOZIRGI QUVVAT", f"{(p or 0) / 1000:.0f} kVt"
        p_note = (f"oxirgi o'lchov {ts.astimezone(TZ):%H:%M}" if offline
                  else "elektr tarmog'idan olinmoqda")
        s_label, m_label, w = "BUGUNGI SARF", "OY BOSHIDAN", "bugun"
    else:
        tag = ""
        title = f"{day.day}-{MONTHS[day.month - 1]} {day.year}{tag}"
        p_label, p_val = "O'RTACHA QUVVAT", f"{avg_w / 1000:.0f} kVt"
        p_note = "shu kuni o'rtacha"
        s_label, m_label, w = "KUNLIK SARF", "OY BOSHIDAN SHU KUNGACHA", "shu kuni"

    return {
        "title": title, "status": status, "head": head, "sub": sub, "w": w,
        "stop": d(stop), "stop_s": stop,
        "p_label": p_label, "p_val": p_val, "p_note": p_note,
        "s_label": s_label, "m_label": m_label,
        "kwh": sum(day_data.values()), "som": cost(day_data, day), "pct": pct,
        "mkwh": sum(float(k or 0) for _, k in month_rows),
        "msom": sum(float(k or 0) * band_for_hour(h.hour, h.date())[1] for h, k in month_rows),
        "n_ev": n_ev,
        "unseen": d(max((min(now, day1) - day0).total_seconds() - covered, 0)),
    }


def xulosa_images(arg=None):
    today = dt.datetime.now(TZ).date()
    day = parse_day(arg, today)
    if day > today:
        return []
    x = data(day)
    if not x:
        return []
    w = x["w"]
    colors = {"green": "#2e9e5b", "yellow": "#e0a100", "red": "#d64545"}
    accent = colors[x["status"]]
    ok = x["stop_s"] < 60
    f_t = ImageFont.truetype(FONT_B, 36)
    f_h = ImageFont.truetype(FONT_B, 50)
    f_s = ImageFont.truetype(FONT, 28)
    f_l = ImageFont.truetype(FONT_B, 24)
    f_b = ImageFont.truetype(FONT_B, 58)
    f_c = ImageFont.truetype(FONT, 27)

    green, red = "#2e9e5b", "#d64545"
    cards = [
        ("KOMPRESSOR", "To'xtamadi" if ok else x["stop"],
         green if ok else red,
         [f"{w} kompressor uzluksiz ishladi"] if ok else [f"{w} to'xtab turgan vaqt"],
         green if ok else red),
        (x["p_label"], x["p_val"], "#111111", [x["p_note"]], "#3b6fd4"),
        (x["s_label"], f"{money(x['som'])} so'm", "#111111",
         [f"{money(x['kwh'])} kVt·soat"], "#8a5cd0"),
        (x["m_label"], f"{money(x['msom'])} so'm", "#111111",
         [f"{money(x['mkwh'])} kVt·soat"], "#e07b2e"),
        ("NOODATIY HOLATLAR", f"{x['n_ev']} ta" if x["n_ev"] else "Yo'q",
         red if x["n_ev"] else green,
         [f"{w} aniqlangan"] if x["n_ev"] else [f"{w} noodatiy holat bo'lmadi"],
         red if x["n_ev"] else green),
        ("NAZORAT TO'XTAGAN", x["unseen"], "#111111",
         ["bot o'chiq bo'lgan vaqt"], "#8a8f98"),
    ]
    if x["pct"] is not None:
        arrow = "ko'p ↑" if x["pct"] > 0 else "kam ↓"
        ref = "kechagiga" if w == "bugun" else "oldingi kunga"
        cards[2][3].append(f"{ref} nisbatan {abs(x['pct']):.0f}% {arrow}")

    W, pad, gap = 800, 32, 20
    banner_h = 170 if x["sub"] else 130
    heights = [150 + 36 * len(c[3]) for c in cards]
    H = pad + 50 + banner_h + gap + sum(h + gap for h in heights) + pad - gap
    img = Image.new("RGB", (W, H), "#eef1f5")
    dr = ImageDraw.Draw(img)

    y = pad
    dr.text((pad, y), x["title"], font=f_t, fill="#222222")
    y += 60
    dr.rounded_rectangle([pad, y, W - pad, y + banner_h], radius=28, fill=accent)
    cy = y + (50 if x["sub"] else banner_h / 2)
    dr.text((W / 2, cy), x["head"], font=f_h, fill="white", anchor="mm")
    if x["sub"]:
        dr.text((W / 2, y + 115), x["sub"], font=f_s, fill="white", anchor="mm")
    y += banner_h + gap

    for (label, big, big_col, caps, bar), h in zip(cards, heights):
        dr.rounded_rectangle([pad, y, W - pad, y + h], radius=22, fill=bar)
        dr.rounded_rectangle([pad + 12, y, W - pad, y + h], radius=22, fill="white")
        tx = pad + 40
        dr.text((tx, y + 22), label, font=f_l, fill="#8a8f98")
        dr.text((tx, y + 58), big, font=f_b, fill=big_col)
        cy = y + 130
        for c in caps:
            dr.text((tx, cy), c, font=f_c, fill="#5a6068")
            cy += 36
        y += h + gap

    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    buf.name = "xulosa.png"
    return [buf]
