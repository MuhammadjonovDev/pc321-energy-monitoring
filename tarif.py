import datetime as dt
from zoneinfo import ZoneInfo

from pc321_db import _connect

TZ = ZoneInfo("Asia/Tashkent")

# (boshlanish soat, tugash soat, narx so'm/kWh, nomi). 30 = ertasi kuni 06:00
BANDS = [
    (6, 9, 1650, "06-09"),
    (9, 17, 733, "09-17"),
    (17, 22, 1650, "17-22"),
    (22, 30, 1100, "22-06"),
]

SQL = """
SELECT date_trunc('hour', ts AT TIME ZONE 'Asia/Tashkent') AS hr,
       SUM(GREATEST(energy_total - prev, 0)) AS kwh
FROM (
    SELECT ts, energy_total,
           LAG(energy_total) OVER (ORDER BY ts) AS prev
    FROM readings
    WHERE ts >= %s AND ts < %s
) t
WHERE prev IS NOT NULL
GROUP BY hr
ORDER BY hr
"""


from tarif_data import band_for_hour  # noqa: E402


def hourly_kwh(day):
    start = dt.datetime.combine(day, dt.time.min, tzinfo=TZ)
    end = start + dt.timedelta(days=1)
    with _connect().cursor() as cur:
        cur.execute(SQL, (start, end))
        return {r[0].hour: float(r[1] or 0) for r in cur.fetchall()}


def money(x):
    return f"{x:,.0f}".replace(",", " ")


def report(day=None):
    day = day or dt.datetime.now(TZ).date()
    data = hourly_kwh(day)
    if not data:
        return f"{day} uchun ma'lumot topilmadi."

    lines = [f"{day}", "", "Soat    kWh     So'm"]
    bands = {}
    total_kwh = 0.0
    total_cost = 0.0

    for h in range(24):
        kwh = data.get(h)
        if kwh is None:
            continue
        name, price = band_for_hour(h, day)
        cost = kwh * price
        lines.append(f"{h:02d}-{(h + 1) % 24:02d}  {kwh:6.2f}  {money(cost):>7}")
        b = bands.setdefault(name, [0.0, 0.0, price])
        b[0] += kwh
        b[1] += cost
        total_kwh += kwh
        total_cost += cost

    lines += ["", "Tarif  Narx   kWh     So'm"]
    for name, (kwh, cost, price) in bands.items():
        lines.append(f"{name}  {price:5d}  {kwh:6.2f}  {money(cost):>7}")

    lines += ["", f"JAMI         {total_kwh:6.2f}  {money(total_cost):>7}"]
    return "<pre>" + "\n".join(lines) + "</pre>"


def month_report(year, month):
    start = dt.datetime(year, month, 1, tzinfo=TZ)
    end = dt.datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=TZ)
    with _connect().cursor() as cur:
        cur.execute(SQL, (start, end))
        rows = cur.fetchall()
    if not rows:
        return f"{year}-{month:02d} uchun ma'lumot topilmadi."

    days = {}
    for hr, kwh in rows:
        kwh = float(kwh or 0)
        price = band_for_hour(hr.hour, hr.date())[1]
        d = days.setdefault(hr.date(), [0.0, 0.0])
        d[0] += kwh
        d[1] += kwh * price

    lines = [f"{year}-{month:02d} oyi", "", "Sana       kWh      So'm"]
    total_kwh = 0.0
    total_cost = 0.0
    for day in sorted(days):
        k, c = days[day]
        lines.append(f"{day.strftime('%m-%d')}   {k:7.2f}  {money(c):>10}")
        total_kwh += k
        total_cost += c

    lines += ["", f"JAMI       {total_kwh:7.2f}  {money(total_cost):>10}"]
    return "<pre>" + "\n".join(lines) + "</pre>"


def oy_report(arg=None):
    if arg:
        y, m = arg.split("-")
        year, month = int(y), int(m)
        if not 1 <= month <= 12:
            raise ValueError("oy noto'g'ri")
    else:
        now = dt.datetime.now(TZ)
        year, month = now.year, now.month
    return month_report(year, month)
