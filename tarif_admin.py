import datetime as dt
import html
import os
import re
import time
from pathlib import Path

import tarif_data as td

BASE = Path(__file__).resolve().parent
PENDING = {}
TTL = 600
DATE_RE = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$")
BAND_RE = re.compile(r"^(\d{1,2})-(\d{1,2})=(\d{2,5})$")


def admin_ids():
    v = os.environ.get("ADMIN_IDS")
    if v is None:
        env = BASE / ".env"
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith("ADMIN_IDS="):
                    v = line.split("=", 1)[1]
    ids = set()
    for x in (v or "").replace(" ", "").split(","):
        if x.lstrip("-").isdigit():
            ids.add(int(x))
    return ids


def _fmt(bands):
    items = sorted(bands, key=lambda b: (b[0] - 6) % 24)
    return "\n".join(f"{td.band_name(s, e)}  {int(p):>6}" for s, e, p in items)


def show(today):
    data = td.load()
    cur = [(vf, b) for vf, b in data if vf <= today][-1]
    title = "Joriy tarif" + ("" if cur[0] == td.EPOCH else f" ({cur[0]} dan)")
    out = [title + ", so'm/kWh:", "<pre>" + _fmt(cur[1]) + "</pre>"]
    for vf, b in data:
        if vf > today:
            out += [f"{vf} dan kuchga kiradi:", "<pre>" + _fmt(b) + "</pre>"]
    return "\n".join(out)


def history():
    conn = td._connect()
    with conn.cursor() as cur:
        cur.execute("""SELECT changed_at AT TIME ZONE 'Asia/Tashkent', admin_id, valid_from,
                              old_bands, new_bands
                       FROM tariff_log ORDER BY id DESC LIMIT 10""")
        rows = cur.fetchall()
    conn.commit()
    if not rows:
        return "Tarif hali o'zgartirilmagan."
    lines = []
    for at, adm, vf, old, new in rows:
        om = {td.band_name(s, e): p for s, e, p in old}
        nm = {td.band_name(s, e): p for s, e, p in new}
        if set(om) == set(nm):
            ch = ", ".join(f"{k} {om[k]}->{nm[k]}" for k in nm if om[k] != nm[k]) or "o'zgarishsiz"
        else:
            ch = "yangi jadval"
        lines.append(f"{at:%d.%m %H:%M} | {adm} | {vf} dan | {ch}")
    return "<pre>" + html.escape("\n".join(lines)) + "</pre>"


def _split_date(items, today):
    if items and DATE_RE.match(items[-1]):
        y, m, d = map(int, DATE_RE.match(items[-1]).groups())
        try:
            day = dt.date(y, m, d)
        except ValueError:
            return None, items, "Sana noto'g'ri."
        if day < dt.date(2020, 1, 1):
            return None, items, "Sana juda eski."
        return day, items[:-1], None
    return today, items, None


def narx_command(cid, text):
    cid = int(cid)
    args = text.split()[1:]
    today = dt.datetime.now(td.TZ).date()
    if not args:
        return show(today)
    sub = args[0].lower()
    if cid not in admin_ids():
        return "Ruxsat yo'q. Tarifni faqat adminlar o'zgartira oladi."
    if sub == "tarix":
        return history()
    if sub in ("yoq", "bekor"):
        PENDING.pop(cid, None)
        return "Bekor qilindi, tarif o'zgarmadi."
    if sub in ("ha", "tasdiq"):
        p = PENDING.pop(cid, None)
        if not p or time.time() - p[2] > TTL:
            return "Kutilayotgan o'zgarish yo'q yoki vaqti o'tdi. /narx buyrug'ini qaytadan yozing."
        td.save(cid, p[0], p[1])
        return f"Saqlandi. Yangi tarif {p[0]} dan kuchga kirdi."

    if sub == "yangi":
        day, items, err = _split_date(args[1:], today)
        if err:
            return err
        bands = []
        for it in items:
            m = BAND_RE.match(it)
            if not m:
                return "Format: /narx yangi 22-06=1100 06-09=1650 09-17=733 17-22=1650 [sana]"
            bands.append([int(m.group(1)), int(m.group(2)), int(m.group(3))])
        if not bands:
            return "Format: /narx yangi 22-06=1100 06-09=1650 09-17=733 17-22=1650 [sana]"
    else:
        day, items, err = _split_date(args, today)
        if err:
            return err
        bands = [list(b) for b in td.bands_for(day)]
        names = {td.band_name(s, e): i for i, (s, e, _) in enumerate(bands)}
        if not items:
            return "Format: /narx 09-17=800 [sana]"
        for it in items:
            m = BAND_RE.match(it)
            if not m:
                return "Format: /narx 09-17=800 [sana]"
            name = td.band_name(int(m.group(1)), int(m.group(2)))
            if name not in names:
                return f"Bunday band yo'q: {html.escape(name)}. Mavjud: " + ", ".join(names)
            bands[names[name]][2] = int(m.group(3))

    err = td.validate(bands)
    if err:
        return err
    old = td.bands_for(day)
    if td.same(old, bands):
        return "Narxlar o'zgarmadi (xuddi shu tarif)."
    PENDING[cid] = (day, bands, time.time())
    out = [f"Yangi tarif ({day} dan):", "<pre>" + _fmt(bands) + "</pre>",
           "Hozirgi:", "<pre>" + _fmt(old) + "</pre>"]
    if day <= today:
        out.append(f"Diqqat: {day} dan boshlab hisobotlar (o'tgan soatlar ham) yangi narx bilan qayta hisoblanadi.")
    out.append("Tasdiqlash: /narx ha\nBekor qilish: /narx yoq\n(10 daqiqa ichida)")
    return "\n".join(out)
