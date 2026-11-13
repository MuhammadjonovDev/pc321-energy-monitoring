import datetime as dt
import json
import time
from zoneinfo import ZoneInfo

from pc321_db import _connect

TZ = ZoneInfo("Asia/Tashkent")
EPOCH = dt.date(2000, 1, 1)
# [boshlanish soat, tugash soat, narx]. Tugash boshlanishdan kichik bo'lsa, ertasi kuni
DEFAULT = [[6, 9, 1650], [9, 17, 733], [17, 22, 1650], [22, 6, 1100]]
MIN_PRICE = 100
MAX_PRICE = 10000

_cache = {"t": 0.0, "rows": None}
_ready = {"ok": False}


def band_name(s, e):
    return f"{s:02d}-{e % 24:02d}"


def ensure_tables(conn):
    with conn.cursor() as cur:
        cur.execute("""CREATE TABLE IF NOT EXISTS tariff (
            valid_from DATE PRIMARY KEY,
            bands JSONB NOT NULL,
            changed_by BIGINT,
            changed_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
        cur.execute("""CREATE TABLE IF NOT EXISTS tariff_log (
            id BIGSERIAL PRIMARY KEY,
            changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            admin_id BIGINT,
            valid_from DATE,
            old_bands JSONB,
            new_bands JSONB)""")
        cur.execute(
            "INSERT INTO tariff (valid_from, bands) VALUES (%s, %s::jsonb) ON CONFLICT DO NOTHING",
            (EPOCH, json.dumps(DEFAULT)))
    conn.commit()


def load():
    """[(valid_from, bands), ...] sana bo'yicha o'sish tartibida."""
    now = time.time()
    if _cache["rows"] is not None and now - _cache["t"] < 30:
        return _cache["rows"]
    conn = None
    try:
        conn = _connect()
        if not _ready["ok"]:
            ensure_tables(conn)
            _ready["ok"] = True
        with conn.cursor() as cur:
            cur.execute("SELECT valid_from, bands FROM tariff ORDER BY valid_from")
            data = [(r[0], r[1]) for r in cur.fetchall()]
        conn.commit()
        _cache["t"] = now
        _cache["rows"] = data
        return data
    except Exception as e:
        print("Tarif jadvali xatosi:", e)
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        return _cache["rows"] or [(EPOCH, DEFAULT)]


def bands_for(day=None):
    if day is None:
        day = dt.datetime.now(TZ).date()
    if isinstance(day, dt.datetime):
        day = day.date()
    cur = DEFAULT
    for vf, b in load():
        if vf <= day:
            cur = b
        else:
            break
    return cur


def hours_map(bands):
    m = {}
    for s, e, price in bands:
        n = (e - s) % 24 or 24
        name = band_name(s, e)
        for k in range(n):
            m[(s + k) % 24] = (name, int(price))
    return m


def band_for_hour(h, day=None):
    return hours_map(bands_for(day)).get(int(h) % 24, ("?", 0))


def validate(bands):
    seen = set()
    for s, e, price in bands:
        if not (0 <= s <= 23 and 0 <= e <= 24):
            return "Soat 0 dan 24 gacha bo'lishi kerak."
        if not (MIN_PRICE <= price <= MAX_PRICE):
            return f"Narx {MIN_PRICE} dan {MAX_PRICE} so'mgacha bo'lishi kerak ({price})."
        n = (e - s) % 24 or 24
        for k in range(n):
            h = (s + k) % 24
            if h in seen:
                return f"{h:02d}:00 soati ikki marta kiritilgan (bandlar ustma-ust)."
            seen.add(h)
    missing = [h for h in range(24) if h not in seen]
    if missing:
        return "Qoplanmagan soatlar: " + ", ".join(f"{h:02d}" for h in missing)
    return None


def same(a, b):
    return sorted(map(tuple, a)) == sorted(map(tuple, b))


def save(admin_id, valid_from, bands):
    old = bands_for(valid_from)
    conn = _connect()
    try:
        ensure_tables(conn)
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO tariff (valid_from, bands, changed_by) VALUES (%s, %s::jsonb, %s)
                   ON CONFLICT (valid_from) DO UPDATE
                   SET bands = EXCLUDED.bands, changed_by = EXCLUDED.changed_by, changed_at = now()""",
                (valid_from, json.dumps(bands), admin_id))
            cur.execute(
                """INSERT INTO tariff_log (admin_id, valid_from, old_bands, new_bands)
                   VALUES (%s, %s, %s::jsonb, %s::jsonb)""",
                (admin_id, valid_from, json.dumps(old), json.dumps(bands)))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    _cache["rows"] = None
