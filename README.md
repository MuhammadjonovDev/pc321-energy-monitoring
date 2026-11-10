# PC321 Energy Monitoring

To'quv sexidagi kompressorlarning elektr energiya sarfini monitoring qilish uchun Telegram bot.

## Loyiha haqida

Tizim PC321-W-TY uch fazali elektr energiya hisoblagichi orqali kompressorning elektr ko'rsatkichlarini kuzatadi, PostgreSQL ga yozadi va Telegram orqali hisobot beradi.

Sexda 2 ta Kaeser kompressori mavjud. Har bir kompressor 132 kW quvvatga ega.

## Imkoniyatlar

- Elektr energiya sarfini real vaqt rejimida kuzatish
- Kuchlanish va tok ko'rsatkichlarini ko'rish
- Fazalar bo'yicha ma'lumot olish
- Kunlik, oylik va yillik hisobotlar
- Elektr energiya xarajatlarini hisoblash (tarif bo'yicha)
- Hodisalar tarixini ko'rish
- Grafik va tahliliy xulosalar
- Bazaning kunlik shifrlangan zaxirasi (Telegram orqali)

## Tizim tuzilishi

```
[Kompressor] -> [PC321 hisoblagich] --Wi-Fi, TCP 6668--> [Ubuntu server]
                                                            |-- PostgreSQL (power)
                                                            |-- pc321bot (systemd)
                                                            |-- zaxira.sh (cron, 03:00)
```

## Telegram buyruqlari

| Buyruq | Vazifasi |
|---|---|
| `/start` | Botga obuna bo'lish |
| `/status` | Joriy holat |
| `/phases` | Fazalar ma'lumotlari |
| `/today` | Kunlik hisobot |
| `/tarif` | Tarif bo'yicha hisob |
| `/oy` | Oylik hisobot |
| `/faoliyat` | Faoliyat hisoboti |
| `/hodisalar` | Hodisalar tarixi |
| `/xulosa` | Tahliliy xulosa |
| `/uskuna` | Uskuna ma'lumotlari |
| `/yillik` | Yillik hisobot |

## Texnologiyalar

- Python 3.12
- PostgreSQL 16
- Ubuntu Server 24.04
- Telegram Bot API
- PC321-W-TY energy meter (tinytuya, protokol 3.5)

## O'rnatish (yangi serverga)

### 1. Dasturlar

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip postgresql nmap fonts-dejavu-core
sudo timedatectl set-timezone Asia/Tashkent
```

### 2. Loyihani yuklash

```bash
sudo git clone https://github.com/MuhammadjonovDev/pc321-energy-monitoring.git /opt/pc321
sudo chown -R $USER:$USER /opt/pc321
cd /opt/pc321
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Baza

Parolda `!`, `$`, tirnoq va probel ishlatmang.

```bash
sudo -u postgres psql -c "CREATE USER pc321 WITH PASSWORD 'PAROL';"
sudo -u postgres psql -c "CREATE DATABASE power OWNER pc321;"
psql -h localhost -U pc321 -d power -W
```

Keyin jadvalni yarating:

```sql
CREATE TABLE IF NOT EXISTS readings (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    device TEXT NOT NULL,
    v_a DOUBLE PRECISION, v_b DOUBLE PRECISION, v_c DOUBLE PRECISION,
    i_a DOUBLE PRECISION, i_b DOUBLE PRECISION, i_c DOUBLE PRECISION,
    p_a DOUBLE PRECISION, p_b DOUBLE PRECISION, p_c DOUBLE PRECISION,
    p_total DOUBLE PRECISION,
    energy_total DOUBLE PRECISION,
    freq DOUBLE PRECISION,
    temp DOUBLE PRECISION,
    raw JSONB
);
CREATE INDEX IF NOT EXISTS idx_readings_ts ON readings (ts);
```

`events` jadvalini bot o'zi yaratadi.

### 4. Qurilmani topish

Hisoblagich IP si o'zgarib turadi. Port 6668 ochiq qurilmani toping:

```bash
sudo nmap -Pn -p 6668 --open 192.168.104.0/22 192.168.108.0/24 192.168.109.0/24 192.168.110.0/24
nc -zv -w 5 QURILMA_IP 6668
```

### 5. Maxfiy fayllar (GitHub'da yo'q)

| Fayl | Qanday olinadi |
|---|---|
| `devices.json`, `tinytuya.json` | `python3 -m tinytuya wizard` (iot.tuya.com Access ID, Secret, Device ID, region) |
| `.env` | Quyidagi kalitlar bilan qo'lda |
| `subscribers_env.json` | Bot o'zi yaratadi (foydalanuvchilar `/start` yozganda) |

`devices.json` dagi birinchi qurilma (`[0]`) PC321 bo'lishi kerak.

`.env` kalitlari:

```
DEVICE_IP=
TG_TOKEN=
REPORT_MINUTES=60
POWER_ALERT_W=160000
CT_MAX_A=750
SAVE_INTERVAL=10
COMP_STOP_W=10000
COMP_LOAD_W=100000
V_MIN=198
V_MAX=242
DB_HOST=localhost
DB_PORT=5432
DB_NAME=power
DB_USER=pc321
DB_PASSWORD=
BACKUP_TG_TOKEN=
BACKUP_PASS=
```

Qoidalar: `=` dan keyin probel, tirnoq bo'lmasin; har kalit alohida qatorda bo'lsin. Keyin:

```bash
chmod 600 .env devices.json tinytuya.json
```

Qiymatsiz ko'rish: `sed -E 's/=.*/=<qiymat>/' .env`

### 6. Doimiy xizmat (systemd)

```bash
sudo tee /etc/systemd/system/pc321bot.service <<'EOF'
[Unit]
Description=PC321 bot
After=network-online.target postgresql.service

[Service]
User=ts
WorkingDirectory=/opt/pc321
ExecStart=/opt/pc321/venv/bin/python3 /opt/pc321/pc321_bot.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now pc321bot
sudo systemctl status pc321bot --no-pager | head -5
journalctl -u pc321bot -n 30 --no-pager
```

Bot systemd da ishlayotganda uni qo'lda ishga tushirmang (qurilmaga ikkita ulanish to'qnashadi).

## Zaxira (backup)

`zaxira.sh` har kuni 03:00 da bazadan nusxa oladi, `gzip` bilan siqadi, `openssl` (AES-256) bilan shifrlaydi va **alohida zaxira boti** orqali Telegram'ga yuboradi. Serverda oxirgi 30 kun saqlanadi (`/home/ts/zaxira/`).

Sozlash:

1. @BotFather da alohida bot yarating, tokenini `.env` ga `BACKUP_TG_TOKEN` qilib yozing.
2. Botga `/start` yozing va chat ID ni oling: `curl -s "https://api.telegram.org/bot${BACKUP_TG_TOKEN}/getUpdates"`
3. `zaxira.sh` ichidagi `CHAT=` qatoriga o'z chat ID ingizni yozing.
4. `.env` ga `BACKUP_PASS` (shifrlash kaliti) qo'shing va **daftarga yozib qo'ying**. Usiz zaxirani ochib bo'lmaydi.
5. Cron:

```bash
chmod 700 /opt/pc321/zaxira.sh
crontab -e
# 0 3 * * * /opt/pc321/zaxira.sh >> /home/ts/zaxira/log.txt 2>&1
```

Qo'lda sinash: `/opt/pc321/zaxira.sh`

### Zaxiradan tiklash

```bash
openssl enc -d -aes-256-cbc -pbkdf2 -pass pass:KALIT_SOZ -in power_YYYY-MM-DD.sql.gz.enc | gunzip | PGPASSWORD='PAROL' psql -h localhost -U pc321 -d power
```

Telegram'dagi fayllarni oyiga bir marta o'z kompyuteringizga ham yuklab oling.

## Tez-tez uchraydigan muammolar

| Belgi | Sabab | Yechim |
|---|---|---|
| `Could not resolve host` | DNS sozlanmagan | `/etc/resolv.conf` ga `nameserver 8.8.8.8` |
| `apt` 404 xatosi | Paketlar ro'yxati eskirgan | `sudo apt update` |
| Qurilmaga `nc` timeout | Qurilma IP si o'zgargan | `nmap` bilan toping, `.env` dagi `DEVICE_IP` ni yangilang, `sudo systemctl restart pc321bot` |
| `905 Device Unreachable` | IP da qurilma yo'q | Yangi IP ni toping |
| `914 Check device key` | Local key eskirgan | `python3 -m tinytuya wizard` |
| `no password supplied` | `.env` da `DB_PASSWORD` bo'sh yoki probel | Parolni to'g'rilang |
| `event not found` (bash) | Parolda `!` bor | `!` siz parol tanlang |
| Telegram `getMe` 404 | `TG_TOKEN` noto'g'ri | Tokenni @BotFather dan qayta oling |

## Xavfsizlik

- `.env`, `devices.json`, `tinytuya.json`, `subscribers_env.json`, `*.sql`, `*.enc` `.gitignore` da, GitHub'ga yuklanmaydi.
- Token, parol va kalitlarni chatga yoki repoga yozmang. Chatga tushgan bo'lsa, almashtiring.
- PostgreSQL portini (5432) internetga ochmang.
- Routerda hisoblagich MAC manziliga doimiy IP (DHCP reservation) biriktiring.

<a href="https://t.me/comressor_test_bot"><img src="https://img.shields.io/badge/Project_bot-26A5E4?style=flat-square&logo=telegram&logoColor=white" /></a>
