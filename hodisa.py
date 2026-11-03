import collections
import datetime as dt
import os
import statistics
import time
from zoneinfo import ZoneInfo

from pc321_db import _connect

TZ = ZoneInfo("Asia/Tashkent")
V_MIN = float(os.environ.get("V_MIN", "198"))
V_MAX = float(os.environ.get("V_MAX", "242"))
SPIKE_PCT = float(os.environ.get("SPIKE_PCT", "0.5"))
SPIKE_MIN_W = float(os.environ.get("SPIKE_MIN_W", "1000"))
REV_W = float(os.environ.get("REV_W", "200"))
SAMPLE_S = 10        # tekshiruv oralig'i, soniya
CONFIRM = 2          # ketma-ket necha tekshiruvdan keyin hodisa ochiladi/yopiladi
MIN_HIST = 30        # sakrash bazasi uchun minimal o'lchovlar (5 daqiqa)

PHASES = {"A": ("101", "103"), "B": ("111", "113"), "C": ("121", "123")}
HIST = {p: collections.deque(maxlen=60) for p in PHASES}   # oxirgi 10 daqiqa
open_ev = {}
pend = collections.Counter()
last_sample = 0.0

KIND_NAMES = {
    "sakrash": "quvvat sakrashi",
    "teskari": "teskari oqim",
    "kuchlanish": "kuchlanish",
    "aloqa": "aloqa",
}


def _fmt(kind, v):
    if v is None:
        return ""
    if kind == "kuchlanish":
        return f"{v:.1f} V"
    return f"{v / 1000:.2f} kW"


def init_events():
    try:
        with _connect().cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id          BIGSERIAL PRIMARY KEY,
                    kind        TEXT NOT NULL,
                    phase       TEXT,
                    started_at  TIMESTAMPTZ NOT NULL,
                    ended_at    TIMESTAMPTZ,
                    peak_value  DOUBLE PRECISION,
                    note        TEXT
                )""")
            cur.execute("UPDATE events SET ended_at = now(), note = 'bot qayta ishga tushdi' "
                        "WHERE ended_at IS NULL")
    except Exception as e:
        print("Hodisa jadvali xatosi:", e)


def _open(kind, phase, value, score, label, notify):
    now = dt.datetime.now(TZ)
    ev_id = None
    try:
        with _connect().cursor() as cur:
            cur.execute("INSERT INTO events (kind, phase, started_at, peak_value) "
                        "VALUES (%s, %s, now(), %s) RETURNING id", (kind, phase, value))
            ev_id = cur.fetchone()[0]
    except Exception as e:
        print("Hodisa yozishda xato:", e)
    open_ev[(kind, phase)] = {"id": ev_id, "started": now, "value": value,
                              "score": score, "label": label}
    if notify:
        extra = f"\nQiymat: {_fmt(kind, value)}" if value is not None else ""
        notify(f"⚠️ {label}\nVaqt: {now:%d.%m %H:%M:%S}{extra}")


def _close(key, notify):
    st = open_ev.pop(key, None)
    if not st:
        return
    now = dt.datetime.now(TZ)
    try:
        if st["id"]:
            with _connect().cursor() as cur:
                cur.execute("UPDATE events SET ended_at = now(), peak_value = %s WHERE id = %s",
                            (st["value"], st["id"]))
    except Exception as e:
        print("Hodisa yopishda xato:", e)
    mins = int((now - st["started"]).total_seconds() // 60)
    if notify:
        notify(f"✅ {st['label']} tugadi\nDavomiyligi: {mins} daqiqa")


def _step(kind, phase, cond, value, score, label, notify):
    key = (kind, phase)
    if key in open_ev:
        st = open_ev[key]
        if cond:
            pend[key] = 0
            if score > st["score"]:
                st["score"], st["value"] = score, value
        else:
            pend[key] += 1
            if pend[key] >= CONFIRM:
                pend[key] = 0
                _close(key, notify)
    else:
        if cond:
            pend[key] += 1
            if pend[key] >= CONFIRM:
                pend[key] = 0
                _open(kind, phase, value, score, label, notify)
        else:
            pend[key] = 0


def check_events(state, notify=None):
    global last_sample
    if time.time() - last_sample < SAMPLE_S:
        return
    last_sample = time.time()

    for ph, (vdp, pdp) in PHASES.items():
        v_raw = state.get(vdp)
        v = None if v_raw is None else v_raw / 10
        w = state.get(pdp)

        if v is not None:
            dev = max(V_MIN - v, v - V_MAX, 0.0)
            _step("kuchlanish", ph, dev > 0, v, dev,
                  f"{ph} faza: kuchlanish me'yordan chiqdi", notify)

        if w is None:
            continue

        _step("teskari", ph, w < -REV_W, w, -w,
              f"{ph} faza: teskari oqim (tarmoqqa qaytmoqda)", notify)

        if len(HIST[ph]) >= MIN_HIST:
            base = statistics.median(HIST[ph])
            thr = max(SPIKE_PCT * abs(base), SPIKE_MIN_W)
            dev_w = w - base
            _step("sakrash", ph, abs(dev_w) > thr, w, abs(dev_w),
                  f"{ph} faza: quvvat keskin o'zgardi", notify)

        if ("sakrash", ph) not in open_ev:
            HIST[ph].append(w)


def set_offline(flag, notify=None):
    key = ("aloqa", None)
    if flag and key not in open_ev:
        _open("aloqa", None, None, 0, "Qurilma bilan aloqa uzildi", notify)
    elif not flag and key in open_ev:
        _close(key, notify)


def events_report(arg=None):
    day = None
    if arg:
        try:
            day = dt.date.fromisoformat(arg)
        except ValueError:
            return "Format: /hodisalar yoki /hodisalar 2026-10-29"
    where, params, title = "", (), "Oxirgi hodisalar"
    if day:
        start = dt.datetime.combine(day, dt.time.min, tzinfo=TZ)
        where = "WHERE started_at >= %s AND started_at < %s"
        params = (start, start + dt.timedelta(days=1))
        title = f"{day} hodisalari"
    try:
        with _connect().cursor() as cur:
            cur.execute(f"""
                SELECT kind, phase,
                       started_at AT TIME ZONE 'Asia/Tashkent',
                       ended_at AT TIME ZONE 'Asia/Tashkent',
                       peak_value
                FROM events {where}
                ORDER BY started_at DESC LIMIT 30""", params)
            rows = cur.fetchall()
    except Exception as e:
        return f"Xato: {e}"
    if not rows:
        return "Hodisa topilmadi."
    lines = [title, ""]
    for kind, phase, s, e, val in rows:
        when = f"{s:%m-%d %H:%M}-{e:%H:%M}" if e else f"{s:%m-%d %H:%M} (davom etmoqda)"
        lines.append(when)
        lines.append(f"  {phase or '-'} {KIND_NAMES.get(kind, kind)} {_fmt(kind, val)}".rstrip())
        lines.append("")
    return "\n".join(lines).rstrip()
