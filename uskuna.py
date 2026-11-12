import os
import requests
from pathlib import Path

BASE = Path(__file__).resolve().parent
PHOTO = BASE / "uskuna.jpg"

TEXT = """ To'quv sexi: havo tizimi

Kompressorlar: 2 ta, bir xil quvvat, har biri 132 kVt
Model: Kaeser DSD 240 T
Inv raqami: —
Xarid narxi: 46 500 €
Ishga tushirilgan muddati: 2021 yil, oktyabr
Ishlab chiqaruvchi: Kaeser

Ishlash prinsipi
Har bir kompressorda 132 kVt li dvigatel bor. Havo vintning aylanishi hisobiga hosil qilinadi.

 Vazifasi
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


def uskuna_send(chat_id):
    """Rasm + matn bitta xabarda. Rasm yo'q yoki xato bo'lsa, faqat matn."""
    token = _token()
    if token and PHOTO.exists() and len(TEXT) <= 1024:
        try:
            with open(PHOTO, "rb") as f:
                r = requests.post(
                    f"https://api.telegram.org/bot{token}/sendPhoto",
                    data={"chat_id": chat_id, "caption": TEXT},
                    files={"photo": f},
                    timeout=30,
                )
            if r.ok:
                return True
            print("uskuna rasm xatosi:", r.status_code, r.text[:200])
        except Exception as e:
            print("uskuna rasm xatosi:", e)
    if token:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": TEXT},
            timeout=15,
        )
    return False
