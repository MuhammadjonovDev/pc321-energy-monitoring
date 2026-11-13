import datetime as dt
import io

from PIL import Image, ImageDraw, ImageFont

from pc321_db import _connect
from tarif import SQL, TZ, band_for_hour, hourly_kwh, money

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
_m = ImageDraw.Draw(Image.new("RGB", (1, 1)))


def render(title, headers, rows, footer=None):
    f = ImageFont.truetype(FONT, 26)
    fb = ImageFont.truetype(FONT_B, 26)
    ft = ImageFont.truetype(FONT_B, 32)
    pad, row_h = 24, 44
    table = [headers] + rows + ([footer] if footer else [])
    widths = [max(_m.textlength(str(r[i]), font=f) for r in table) + 40
              for i in range(len(headers))]
    W = int(sum(widths) + 2 * pad)
    H = int(pad * 2 + 50 + row_h * len(table))
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    d.text((pad, pad), title, font=ft, fill="black")
    y = pad + 50
    for ri, r in enumerate(table):
        bold = ri == 0 or (footer is not None and ri == len(table) - 1)
        if bold:
            d.rectangle([pad, y, W - pad, y + row_h], fill="#e8eef7")
        font = fb if bold else f
        x = pad
        for i, cell in enumerate(r):
            text = str(cell)
            tw = _m.textlength(text, font=font)
            tx = x + 20 if i == 0 else x + widths[i] - 20 - tw
            d.text((tx, y + 9), text, font=font, fill="black")
            x += widths[i]
        y += row_h
        d.line([pad, y, W - pad, y], fill="#dddddd")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    buf.name = "hisobot.png"
    return buf


def day_images(day=None):
    day = day or dt.datetime.now(TZ).date()
    data = hourly_kwh(day)
    if not data:
        return []
    rows, bands, tk, tc = [], {}, 0.0, 0.0
    for h in range(24):
        if h not in data:
            continue
        kwh = data[h]
        name, price = band_for_hour(h, day)
        cost = kwh * price
        rows.append([f"{h:02d}-{(h + 1) % 24:02d}", str(price), f"{kwh:.2f}", money(cost)])
        b = bands.setdefault(name, [0.0, 0.0, price])
        b[0] += kwh
        b[1] += cost
        tk += kwh
        tc += cost
    hourly = render(f"{day} soatlik", ["Soat", "Narx", "kWh", "So'm"], rows,
                    ["JAMI", "", f"{tk:.2f}", money(tc)])
    summary = render(f"{day} tarif bo'yicha", ["Tarif", "Narx", "kWh", "So'm"],
                     [[n, str(p), f"{k:.2f}", money(c)] for n, (k, c, p) in bands.items()],
                     ["JAMI", "", f"{tk:.2f}", money(tc)])
    return [hourly, summary]


def month_images(arg=None):
    if arg:
        y, m = arg.split("-")
        year, month = int(y), int(m)
        if not 1 <= month <= 12:
            raise ValueError("oy noto'g'ri")
    else:
        now = dt.datetime.now(TZ)
        year, month = now.year, now.month
    start = dt.datetime(year, month, 1, tzinfo=TZ)
    end = dt.datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=TZ)
    with _connect().cursor() as cur:
        cur.execute(SQL, (start, end))
        rows = cur.fetchall()
    if not rows:
        return []
    days = {}
    for hr, kwh in rows:
        kwh = float(kwh or 0)
        d = days.setdefault(hr.date(), [0.0, 0.0])
        d[0] += kwh
        d[1] += kwh * band_for_hour(hr.hour, hr.date())[1]
    tr = [[day.strftime("%d.%m"), f"{k:.2f}", money(c)] for day, (k, c) in sorted(days.items())]
    tk = sum(v[0] for v in days.values())
    tc = sum(v[1] for v in days.values())
    return [render(f"{year}-{month:02d} oyi", ["Sana", "kWh", "So'm"], tr,
                   ["JAMI", f"{tk:.2f}", money(tc)])]


def year_images(arg=None):
    now = dt.datetime.now(TZ)
    try:
        year = int(arg) if arg else now.year
    except ValueError:
        raise ValueError("yil noto'g'ri")
    if not 2000 <= year <= 2100:
        raise ValueError("yil noto'g'ri")
    start = dt.datetime(year, 1, 1, tzinfo=TZ)
    end = dt.datetime(year + 1, 1, 1, tzinfo=TZ)
    with _connect().cursor() as cur:
        cur.execute(SQL, (start, end))
        rows = cur.fetchall()
    if not rows:
        return []
    names = ["Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun", "Iyul",
             "Avgust", "Sentabr", "Oktabr", "Noyabr", "Dekabr"]
    months = {}
    for hr, kwh in rows:
        k = float(kwh or 0)
        m = months.setdefault(hr.month, [0.0, 0.0])
        m[0] += k
        m[1] += k * band_for_hour(hr.hour, hr.date())[1]
    tr = [[names[m - 1], f"{k:,.0f}".replace(",", " "), money(c)]
          for m, (k, c) in sorted(months.items())]
    tk = sum(v[0] for v in months.values())
    tc = sum(v[1] for v in months.values())
    return [render(f"{year} yil", ["Oy", "kWh", "So'm"], tr,
                   ["JAMI", f"{tk:,.0f}".replace(",", " "), money(tc)])]
