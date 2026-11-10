#!/bin/bash
set -e
set -a; source /opt/pc321/.env; set +a
DIR=/home/ts/zaxira
mkdir -p $DIR
F=$DIR/power_$(date +%F).sql.gz.enc
CHAT=535028561
API="https://api.telegram.org/bot${BACKUP_TG_TOKEN}"

PGPASSWORD="$DB_PASSWORD" pg_dump -h localhost -U pc321 -d power \
  | gzip \
  | openssl enc -aes-256-cbc -pbkdf2 -salt -pass env:BACKUP_PASS > $F
chmod 600 $F
find $DIR -name 'power_*.enc' -mtime +30 -delete

SIZE=$(stat -c %s $F)
if [ "$SIZE" -lt 49000000 ]; then
  curl -s -F chat_id=$CHAT -F document=@$F -F caption="Zaxira $(date +%F), $((SIZE/1024)) KB" $API/sendDocument > /dev/null
else
  curl -s $API/sendMessage -d chat_id=$CHAT -d text="Zaxira olindi, lekin 50 MB dan katta, Telegramga sigmadi. Fayl serverda: $F" > /dev/null
fi
