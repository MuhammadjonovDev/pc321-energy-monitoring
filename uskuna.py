import os
import json
import requests
from pathlib import Path

BASE = Path(__file__).resolve().parent
MEDIA_DIR = BASE / "uskuna_media"
PHOTO_EXT = {".jpg", ".jpeg", ".png"}
VIDEO_EXT = {".mp4"}
MAX_PHOTO = 10 * 1024 * 1024
MAX_VIDEO = 50 * 1024 * 1024

TEXT = """🏭 To'quv sexi: havo tizimi

Kompressorlar: 2 ta, bir xil quvvat, har biri 132 kVt
Model: Kaeser DSD 240 T
Inv raqami: — Kompressor-1
Xarid narxi: 46 500 €
Ishga tushirilgan sanasi: 2021 yil, oktyabr
Ishlab chiqaruvchi: Kaeser

⚙️ Ishlash prinsipi
Har bir kompressorda 132 kVt li dvigatel bor. Havo vintning aylanishi hisobiga hosil qilinadi. Bu dastur Kompressor-1 uchun

🎯 Vazifasi
To'quv, pechat va yozuv uskunalariga havo berish. Pechat mashinalarida qolip materiallarini havo yordamida yaqinlashtirish va ko'tarish uchun ishlatiladi. Yangi havo bilan ishlaydigan uskunalar ham shu tizimga ulangan."""


def uskuna_info(arg=None):
    return TEXT


def _token():
    t = os.environ.get("TG_TOKEN")
    if t:
        return t.strip()
    env = BASE / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("TG_TOKEN="):
                return line.split("=", 1)[1].strip()
    return None


def _media_files():
    """Papkadagi yaroqli fayllar, nomi bo'yicha tartiblangan, 10 tagacha."""
    if not MEDIA_DIR.is_dir():
        return []
    out = []
    for p in sorted(MEDIA_DIR.iterdir(), key=lambda x: x.name):
        ext = p.suffix.lower()
        size = p.stat().st_size
        if ext in PHOTO_EXT and size <= MAX_PHOTO:
            out.append((p, "photo"))
        elif ext in VIDEO_EXT and size <= MAX_VIDEO:
            out.append((p, "video"))
        elif ext in PHOTO_EXT | VIDEO_EXT:
            print("uskuna: fayl juda katta, o'tkazib yuborildi:", p.name)
    return out[:10]


def _send_text(token, chat_id):
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": TEXT},
        timeout=15,
    )


def uskuna_send(chat_id):
    """Albom (rasmlar + video), matn birinchi elementda. Xato bo'lsa faqat matn."""
    token = _token()
    if not token:
        return False
    items = _media_files()
    if not items or len(TEXT) > 1024:
        _send_text(token, chat_id)
        return False

    api = f"https://api.telegram.org/bot{token}"
    handles = []
    try:
        if len(items) == 1:
            p, kind = items[0]
            f = open(p, "rb")
            handles.append(f)
            method = "sendPhoto" if kind == "photo" else "sendVideo"
            data = {"chat_id": chat_id, "caption": TEXT}
            if kind == "video":
                data["supports_streaming"] = "true"
            r = requests.post(f"{api}/{method}", data=data, files={kind: f}, timeout=180)
        else:
            media, files = [], {}
            for i, (p, kind) in enumerate(items):
                f = open(p, "rb")
                handles.append(f)
                files[f"f{i}"] = f
                m = {"type": kind, "media": f"attach://f{i}"}
                if kind == "video":
                    m["supports_streaming"] = True
                if i == 0:
                    m["caption"] = TEXT
                media.append(m)
            r = requests.post(
                f"{api}/sendMediaGroup",
                data={"chat_id": chat_id, "media": json.dumps(media)},
                files=files,
                timeout=300,
            )
        if r.ok:
            return True
        print("uskuna albom xatosi:", r.status_code, r.text[:200])
    except Exception as e:
        print("uskuna albom xatosi:", e)
    finally:
        for f in handles:
            f.close()
    _send_text(token, chat_id)
    return False
