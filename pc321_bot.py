import json
import os
import sys
import time
from pathlib import Path

import requests
import tinytuya
from pc321_db import save_reading

from datetime import date
from rasm import day_images, month_images, year_images
from hodisa import check_events, init_events, events_report, set_offline
from grafik import hodisa_images
from uskuna import uskuna_info, uskuna_send
from xulosa import xulosa_images
from kompressor import kompressor_report

BASE = Path(__file__).resolve().parent
ENV_FILE = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE / ".env"
if not ENV_FILE.is_absolute():
    ENV_FILE = BASE / ENV_FILE

def load_env():
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


load_env()
TOKEN = os.environ.get("TG_TOKEN", "")
REPORT_MINUTES = int(os.environ.get("REPORT_MINUTES", "60"))
POWER_ALERT_W = float(os.environ.get("POWER_ALERT_W", "0"))
DEVICE_IP = os.environ.get("DEVICE_IP", "").strip()
CT_MAX_A = float(os.environ.get("CT_MAX_A", "750"))
SAVE_INTERVAL = int(os.environ.get("SAVE_INTERVAL", "10"))
DEVICE_NAME = "PC321"
OFFLINE_AFTER = 4

API = f"https://api.telegram.org/bot{TOKEN}"
STEM = ENV_FILE.stem.lstrip(".") or "pc321"
SUBS_FILE = BASE / f"subscribers_{STEM}.json"
DAILY_FILE = BASE / f"daily_{STEM}.json"

# ---------- DP xaritasi ----------
# Variantlar ro'yxati: birinchi mavjud DP olinadi. Quvvat DP lari xom ko'rinishda vatt.
POWER = [{"dp": "133", "scale": 1}, {"sum": ["103", "113", "123"], "scale": 1}]
TOTAL = [{"dp": "131", "scale": 0.01}, {"sum": ["106", "116", "126"], "scale": 0.01}]
FREQ = [{"dp": "135", "scale": 1}]
TEMP = [{"dp": "136", "scale": 0.1}]
PHASES = {  # faza: (kuchlanish, tok mA, quvvat W)
    "A": ("101", "102", "103"),
    "B": ("111", "112", "113"),
    "C": ("121", "122", "123"),
}


def get(state, variants):
    for spec in variants:
        if "sum" in spec:
            got = [state[k] for k in spec["sum"] if k in state]
            if got:
                return sum(got) * spec["scale"]
        elif spec["dp"] in state:
            return state[spec["dp"]] * spec["scale"]
    return None


def fmt(v, digits=0):
    return "?" if v is None else f"{v:.{digits}f}"


# ---------- matn ----------
def max_phase_current(state):
    amps = [state[i] / 1000 for _, i, _ in PHASES.values() if i in state]
    return max(amps) if amps else None


def sensor_warning(state):
    a = max_phase_current(state)
    if a is not None and a > CT_MAX_A * 1.2:
        return (f"⚠️ Tok {a:.0f} A (datchik {CT_MAX_A:.0f} A gacha). Bunday qiymat odatda CT datchik "
                "ulanmaganini yoki noto'g'ri kiydirilganini bildiradi, raqamlarga ishonmang.")
    return None


def status_text(state, daily=None, offline=False):
    p = get(state, POWER)
    lines = ["⚡ PC321"]
    if p is None:
        lines.append("Hozir iste'mol: ? W")
    else:
        note = "  (tarmoqqa qaytmoqda yoki datchik teskari)" if p < 0 else ""
        lines.append(f"Hozir iste'mol: {p:.0f} W{note}")
    if daily is not None:
        lines.append(f"Bugun: {daily:.2f} kWh")
    lines.append(f"Jami sarf: {fmt(get(state, TOTAL), 2)} kWh")
    va, vb = state.get("101"), state.get("111")
    volts = " / ".join(f"{v / 10:.1f}" for v in (va, vb) if v is not None) or "?"
    lines.append(f"Kuchlanish: {volts} V, {fmt(get(state, FREQ))} Hz")
    t = get(state, TEMP)
    if t is not None:
        lines.append(f"Harorat: {t:.1f} °C")
    warn = sensor_warning(state)
    if warn:
        lines.append(warn)
    if offline:
        lines.append("⚠️ Aloqa yo'q, oxirgi ma'lum qiymatlar.")
    return "\n".join(lines)


def phases_text(state):
    lines = ["🔌 Fazalar"]
    for name, (v, i, p) in PHASES.items():
        if v in state or i in state or p in state:
            volt = None if v not in state else state[v] / 10
            amp = None if i not in state else state[i] / 1000
            lines.append(f"{name}: {fmt(state.get(p))} W, {fmt(amp, 2)} A, {fmt(volt, 1)} V")
    if len(lines) == 1:
        lines.append("Ma'lumot hali olinmadi.")
    warn = sensor_warning(state)
    if warn:
        lines.append(warn)
    return "\n".join(lines)


# ---------- kunlik sarf (fayl bilan saqlanadi) ----------
def daily_usage(total):
    if total is None:
        return None
    try:
        import datetime as _dt
        from zoneinfo import ZoneInfo
        from tarif import hourly_kwh
        today = _dt.datetime.now(ZoneInfo("Asia/Tashkent")).date()
        data = hourly_kwh(today)
        if data:
            return sum(data.values())
    except Exception as e:
        print("Kunlik sarf tarifdan olinmadi:", e)
    return _daily_usage_db(total)


def _daily_usage_db(total):
    if total is None:
        return None
    try:
        import datetime as _dt
        from zoneinfo import ZoneInfo
        from pc321_db import _connect
        tz = ZoneInfo("Asia/Tashkent")
        day0 = _dt.datetime.combine(_dt.datetime.now(tz).date(), _dt.time.min, tzinfo=tz)
        with _connect().cursor() as cur:
            cur.execute("SELECT energy_total FROM readings WHERE ts < %s "
                        "ORDER BY ts DESC LIMIT 1", (day0,))
            r = cur.fetchone()
            if r is None:
                cur.execute("SELECT energy_total FROM readings WHERE ts >= %s "
                            "ORDER BY ts LIMIT 1", (day0,))
                r = cur.fetchone()
        if r is not None and r[0] is not None:
            return max(total - float(r[0]), 0.0)
    except Exception as e:
        print("Kunlik sarf bazadan olinmadi:", e)
    return _daily_usage_old(total)


def _daily_usage_old(total):
    if total is None:
        return None
    today = time.strftime("%Y-%m-%d")
    try:
        rec = json.loads(DAILY_FILE.read_text())
    except (OSError, ValueError):
        rec = {}
    if rec.get("date") != today or total < rec.get("start", total):
        rec = {"date": today, "start": total}
        try:
            DAILY_FILE.write_text(json.dumps(rec))
        except OSError:
            pass
    return total - rec["start"]


# ---------- Telegram ----------
def tg_send(chat_id, text, html=False):
    payload = {"chat_id": chat_id, "text": text}
    if html:
        payload["parse_mode"] = "HTML"
    try:
        requests.post(f"{API}/sendMessage", json=payload, timeout=10)
    except requests.RequestException as e:
        print("Telegram yuborishda xato:", e)


def tg_updates(offset):
    try:
        r = requests.get(f"{API}/getUpdates", params={"offset": offset, "timeout": 2}, timeout=10)
        return r.json().get("result", [])
    except (requests.RequestException, ValueError):
        return []


def load_subs():
    try:
        return [str(x) for x in json.loads(SUBS_FILE.read_text())]
    except (OSError, ValueError):
        return []


XULOSA_KB = {"inline_keyboard": [
    [{"text": "⚡ Hozir", "callback_data": "/status"},
     {"text": "🔌 Fazalar", "callback_data": "/phases"}],
    [{"text": "📅 Bugun", "callback_data": "/today"},
     {"text": "💰 Tarif", "callback_data": "/tarif"}],
    [{"text": "📊 Oy", "callback_data": "/oy"},
     {"text": "⏱ Faoliyat", "callback_data": "/faoliyat"}],
    [{"text": "⚠️ Hodisalar", "callback_data": "/hodisalar"}],
]}


def tg_send_photo(chat_id, buf, markup=None):
    import json as _j
    data = {"chat_id": chat_id}
    if markup:
        data["reply_markup"] = _j.dumps(markup)
    try:
        requests.post(f"{API}/sendPhoto", data=data,
                      files={"photo": (buf.name, buf, "image/png")}, timeout=20)
    except requests.RequestException as e:
        print("Telegram rasm xatosi:", e)


def send_images(cid, imgs, markup=None):
    if not imgs:
        tg_send(cid, "Ma'lumot topilmadi.")
        return
    for img in imgs:
        tg_send_photo(cid, img, markup)


import re as _re


def _norm_args(raw):
    p = raw.split(None, 1)
    if len(p) < 2:
        return raw
    a = _re.sub(r"(\d{4})[-/.](\d{1,2})(?:[-/.](\d{1,2}))?",
                lambda m: f"{m[1]}-{int(m[2]):02d}" + (f"-{int(m[3]):02d}" if m[3] else ""),
                p[1])
    return p[0] + " " + a


def _now_tk():
    import datetime as _dt
    from zoneinfo import ZoneInfo
    return _dt.datetime.now(ZoneInfo("Asia/Tashkent")).strftime("%d.%m.%Y %H:%M")


def main():
    if not TOKEN:
        raise SystemExit(f"TG_TOKEN topilmadi. {ENV_FILE.name} fayliga tokenni yozing.")

    subs = load_subs()

    def save_subs():
        SUBS_FILE.write_text(json.dumps(subs))

    def broadcast(text):
        for cid in subs:
            tg_send(cid, text)

    devices = json.loads((BASE / "devices.json").read_text())
    dev = next((x for x in devices if DEVICE_NAME.lower() in x["name"].lower()), None)
    if dev is None:
        raise SystemExit(f"'{DEVICE_NAME}' devices.json da yo'q. Mavjud: " + ", ".join(x["name"] for x in devices))

    ip = DEVICE_IP or dev.get("ip") or "Auto"
    try:
        d = tinytuya.Device(dev["id"], ip, dev["key"])
    except RuntimeError:
        raise SystemExit(
            f"{dev['name']} tarmoqda topilmadi (IP: {ip}).\n"
            "Kompyuter va qurilma bir Wi-Fi da bo'lsin. IP: python3 -m tinytuya scan, "
            f"so'ng {ENV_FILE.name} ga DEVICE_IP=... yozing."
        )
    d.set_version(float(dev.get("version") or 3.5))
    d.set_socketPersistent(True)
    d.set_socketTimeout(3)

    state = {}
    fails, offline, alert_active = 0, False, False
    mark_total, mark_time = None, None
    last_report = time.time()
    offset = 0
    last_save = 0.0

    def read():
        try:
            resp = d.status()
        except Exception as e:  # noqa: BLE001
            print("O'qishda xato:", e)
            return False
        new = resp.get("dps") if isinstance(resp, dict) else None
        if not new:
            print("Qurilma javobi:", resp)
            return False
        state.update(new)
        return True

    print(f"Bot ishga tushdi ({dev['name']}, IP: {ip}). Obunachilar: {len(subs)}. Botga /start yozing. Ctrl+C - to'xtatish")

    init_events()
    while True:
        ok = read()
        if ok:
            fails = 0
            check_events(state, None)
            if time.time() - last_save >= SAVE_INTERVAL:
                save_reading(state)
                last_save = time.time()
            total = get(state, TOTAL)
            if offline:
                offline = False
                set_offline(False, None)
                broadcast("✅ PC321 qayta ulandi.\n" + status_text(state, daily_usage(total)))
            p = get(state, POWER)
            if POWER_ALERT_W > 0 and p is not None:
                if p > POWER_ALERT_W and not alert_active:
                    alert_active = True
                    broadcast(f"🚨 Quvvat limitdan oshdi: {p:.0f} W (limit {POWER_ALERT_W:.0f} W)")
                elif p < POWER_ALERT_W * 0.9 and alert_active:
                    alert_active = False
                    broadcast(f"✅ Quvvat normaga qaytdi: {p:.0f} W")
        else:
            fails += 1
            if fails >= OFFLINE_AFTER and not offline:
                offline = True
                set_offline(True, None)
                broadcast("⚠️ PC321 bilan aloqa uzildi (Wi-Fi, IP yoki kalitni tekshiring).")

        if REPORT_MINUTES > 0 and subs and ok and time.time() - last_report >= REPORT_MINUTES * 60:
            total = get(state, TOTAL)
            text = "📊 Avtomatik hisobot, " + _now_tk() + "\n" + status_text(state, daily_usage(total))
            if total is not None and mark_total is not None:
                text += f"\nO'zgarish ({mark_time} dan beri): +{total - mark_total:.2f} kWh"
            broadcast(text)
            mark_total, mark_time = total, time.strftime("%H:%M")
            last_report = time.time()

        for upd in tg_updates(offset):
            offset = upd["update_id"] + 1
            cb = upd.get("callback_query")
            if cb:
                requests.post(f"{API}/answerCallbackQuery",
                              json={"callback_query_id": cb["id"]}, timeout=10)
                msg = {"text": cb.get("data", ""),
                       "chat": (cb.get("message") or {}).get("chat", {})}
            else:
                msg = upd.get("message") or {}
            raw = (msg.get("text") or "").strip()
            raw = _norm_args(raw)
            text = raw.lower()
            cid = str((msg.get("chat") or {}).get("id", ""))
            if not text or not cid:
                continue

            if text.startswith("/start"):
                if cid in subs:
                    tg_send(cid, "Siz obunasiz. Buyruqlar: /status, /phases, /today, /xulosa")

                else:
                    subs.append(cid)
                    save_subs()
                    print("Yangi obunachi:", cid)
                    tg_send(cid, "✅ Obuna bo'ldingiz. Buyruqlar: /status, /phases, /today, /xulosa")
                continue

            if text.startswith("/stop"):
                if cid in subs:
                    subs.remove(cid)
                    save_subs()
                    tg_send(cid, "Obuna bekor qilindi. Qayta qo'shilish: /start")
                continue

            if cid not in subs:
                continue

            if text.startswith("/tarif"):
                parts = raw.split()
                day = None
                if len(parts) > 1:
                    try:
                        day = date.fromisoformat(parts[1])
                    except ValueError:
                        tg_send(cid, "Format: /tarif yoki /tarif 2026-10-28")
                        continue
                try:
                    send_images(cid, day_images(day))
                except Exception as e:
                    tg_send(cid, f"Hisobotda xato: {e}")
                continue

            if text.startswith("/faoliyat"):
                parts = raw.split()
                try:
                    tg_send(cid, kompressor_report(parts[1] if len(parts) > 1 else None), html=True)
                except Exception as e:
                    tg_send(cid, f"Hisobotda xato: {e}")
                continue
            if text.startswith("/xulosa"):
                try:
                    send_images(cid, xulosa_images(" ".join(raw.split()[1:]) or None), XULOSA_KB)
                except Exception as e:
                    tg_send(cid, f"Hisobotda xato: {e}")
                continue
            if text.startswith("/uskuna"):
                uskuna_send(cid)
                continue
            if text.startswith("/hodisalar"):
                parts = raw.split()
                send_images(cid, hodisa_images(parts[1] if len(parts) > 1 else None))
                continue
            if text.startswith("/yillik"):
                parts = raw.split()
                try:
                    send_images(cid, year_images(parts[1] if len(parts) > 1 else None))
                except ValueError:
                    tg_send(cid, "Format: /yillik yoki /yillik 2026")
                except Exception as e:
                    tg_send(cid, f"Hisobotda xato: {e}")
                continue
            if text.startswith("/oy"):
                parts = raw.split()
                from tarif import oy_report
                try:
                    send_images(cid, month_images(parts[1] if len(parts) > 1 else None))
                except ValueError:
                    tg_send(cid, "Format: /oy yoki /oy 2026-10")
                except Exception as e:
                    tg_send(cid, f"Hisobotda xato: {e}")
                continue

            if text.startswith(("/status", "/phases", "/today")):
                read()  # javob oldidan yangi o'qish
            total = get(state, TOTAL)
            if text.startswith("/status"):
                tg_send(cid, status_text(state, daily_usage(total), offline))
            elif text.startswith("/phases"):
                tg_send(cid, phases_text(state))
            elif text.startswith("/today"):
                used = daily_usage(total)
                tg_send(cid, "Ma'lumot hali olinmadi." if used is None else f"📅 Bugungi sarf: {used:.2f} kWh")


if __name__ == "__main__":
    main()
