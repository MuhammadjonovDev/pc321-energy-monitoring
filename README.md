# PC321 Energy Monitoring

To‘quv sexidagi kompressorlarning elektr energiya sarfini monitoring qilish uchun Telegram bot.

## Loyiha haqida

Tizim PC321-W-TY uch fazali elektr energiya hisoblagichi orqali kompressorning elektr ko‘rsatkichlarini kuzatadi.

Sexda 2 ta Kaeser kompressori mavjud. Har bir kompressor 132 kW quvvatga ega.

## Imkoniyatlar

- Elektr energiya sarfini real vaqt rejimida kuzatish
- Kuchlanish va tok ko‘rsatkichlarini ko‘rish
- Fazalar bo‘yicha ma’lumot olish
- Kunlik va oylik hisobotlar
- Elektr energiya xarajatlarini hisoblash
- Hodisalar tarixini ko‘rish
- Grafik va tahliliy xulosalar

## Telegram buyruqlari

| Buyruq | Vazifasi |
|---|---|
| `/start` | Botni ishga tushirish |
| `/status` | Joriy holat |
| `/phases` | Fazalar ma’lumotlari |
| `/today` | Kunlik hisobot |
| `/tarif` | Tarif bo‘yicha hisob |
| `/oy` | Oylik hisobot |
| `/faoliyat` | Faoliyat hisoboti |
| `/hodisalar` | Hodisalar tarixi |
| `/xulosa` | Tahliliy xulosa |
| `/uskuna` | Uskuna ma’lumotlari |

## Texnologiyalar

- Python
- PostgreSQL
- Ubuntu Server
- Telegram Bot API
- PC321-W-TY energy meter

## O‘rnatish

```bash
git clone https://github.com/MuhammadjonovDev/pc321-energy-monitoring.git
cd pc321-energy-monitoring

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```
<a href="https://t.me/@comressor_test_bot"><img src="https://img.shields.io/badge/Mening_botim-26A5E4?style=flat-square&logo=telegram&logoColor=white" /></a>

