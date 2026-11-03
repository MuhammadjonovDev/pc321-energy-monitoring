import datetime as dt
import os
from zoneinfo import ZoneInfo

from pc321_db import _connect

TZ = ZoneInfo("Asia/Tashkent")
STOP_W = float(os.environ.get("COMP_STOP_W", "10000"))   # undan past = to'xtagan
LOAD_W = float(os.environ.get("COMP_LOAD_W", "100000"))  # undan yuqori = yuk bilan
GAP = 60         # undan katta uzilish = bot o'chiq bo'lgan, soniya
MAX_LINES = 60


def d(x):
    x = int(x)
    h, m, sec = x // 3600, (x % 3600) // 60, x % 60
    if h:
        return f"{h} soat {m} daqiqa"
    if m:
        return f"{m} daqiqa {sec} soniya" if sec else f"{m} daqiqa"
    return f"{sec} soniya"


def hm(t):
    return t.astimezone(TZ).strftime("%H:%M:%S")


def kompressor_report(arg=None):
    try:
        day = dt.date.fromisoformat(arg) if arg else dt.datetime.now(TZ).date()
    except ValueError:
        return "Format: /faoliyat yoki /faoliyat 2026-10-28"
    s = dt.datetime.combine(day, dt.time.min, tzinfo=TZ)
    e = s + dt.timedelta(days=1)
    with _connect().cursor() as cur:
        cur.execute("SELECT ts, p_total FROM readings WHERE ts >= %s AND ts < %s ORDER BY ts", (s, e))
        rows = cur.fetchall()
    if len(rows) < 2:
        return f"{day} uchun ma'lumot yetarli emas."

    tot = [0.0, 0.0, 0.0]    # to'xtagan, yuksiz, yuk bilan
    stops = []
    covered = 0.0
    for (t0, w0), (t1, _) in zip(rows, rows[1:]):
        gap = (t1 - t0).total_seconds()
        if gap > GAP:
            continue
        w = w0 or 0
        st = 0 if w < STOP_W else (1 if w < LOAD_W else 2)
        tot[st] += gap
        covered += gap
        if st == 0:
            if stops and stops[-1][1] == t0:
                stops[-1][1] = t1
            else:
                stops.append([t0, t1])

    now = min(dt.datetime.now(TZ), e)
    unseen = max((now - s).total_seconds() - covered, 0)
    lines = [
        f"<b>Kompressor: {day}</b>", "",
        f"<b>Jami ishladi: {d(tot[1] + tot[2])}</b>",
        f"  Yuk bilan:  {d(tot[2])}",
        f"  Yuksiz:     {d(tot[1])}",
        f"<b>To'xtagan: {d(tot[0])}</b>",
        f"<b>Kuzatilmagan: {d(unseen)}</b> (bot o'chiq)",
    ]
    if stops:
        lines += ["", "To'xtagan vaqtlar:"]
        for a, b in stops[:MAX_LINES]:
            lines.append(f"{hm(a)} - {hm(b)} ({d((b - a).total_seconds())})")
        if len(stops) > MAX_LINES:
            lines.append(f"... yana {len(stops) - MAX_LINES} ta")
    return "\n".join(lines)
