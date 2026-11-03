import json
import os

import psycopg

_conn = None

INSERT_SQL = """
INSERT INTO readings (device, v_a, v_b, v_c, i_a, i_b, i_c,
                      p_a, p_b, p_c, p_total, energy_total,
                      freq, temp, raw)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


def _connect():
    global _conn
    if _conn is None or _conn.closed:
        _conn = psycopg.connect(
            host=os.environ.get("DB_HOST", "localhost"),
            port=int(os.environ.get("DB_PORT", "5432")),
            dbname=os.environ.get("DB_NAME", "power"),
            user=os.environ.get("DB_USER", "pc321"),
            password=os.environ.get("DB_PASSWORD", ""),
            autocommit=True,
        )
    return _conn


def _g(dps, key, scale=1.0):
    v = dps.get(key)
    return None if v is None else v * scale


def _sum(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) if vals else None


def save_reading(dps, device="PC321"):
    """dps - qurilmadan kelgan xom DP lar. Muvaffaqiyatli bo'lsa True qaytaradi."""
    global _conn
    try:
        p_total = _g(dps, "133")
        if p_total is None:
            p_total = _sum([_g(dps, k) for k in ("103", "113", "123")])

        energy = _g(dps, "131", 0.01)
        if energy is None:
            energy = _sum([_g(dps, k, 0.01) for k in ("106", "116", "126")])

        row = (
            device,
            _g(dps, "101", 0.1), _g(dps, "111", 0.1), _g(dps, "121", 0.1),
            _g(dps, "102", 0.001), _g(dps, "112", 0.001), _g(dps, "122", 0.001),
            _g(dps, "103"), _g(dps, "113"), _g(dps, "123"),
            p_total, energy,
            _g(dps, "135"), _g(dps, "136", 0.1),
            json.dumps(dps, sort_keys=True),
        )
        _connect().execute(INSERT_SQL, row)
        return True
    except Exception as e:
        print("Baza xatosi:", e)
        # Ulanish buzilgan bo'lsa, keyingi safar qayta ulanamiz
        try:
            if _conn is not None:
                _conn.close()
        except Exception:
            pass
        _conn = None
        return False
