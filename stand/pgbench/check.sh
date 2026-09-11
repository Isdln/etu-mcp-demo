#!/usr/bin/env bash

set -u

STAND = "${STAND:-/opt/pgmon-stand}"
if [ -f "$STAND/.env" ]; then set -a; . "$STAND/.env"; set +a
else echo "ОШИБКА: нет $STAND/.env"; exit 1; fi

W = "${STAND:-/opt/pgmon-stand}/stand/pgbench"
export PGPASSWORD="$APP_PASSWORD"
pgbench -h "${1:-127.0.0.1}" -p "${2:-6432}" -U app -d bench -c 8 -j 2 -T 30 -R 20 -L 5000 --random-seed=42 -f "$W/q_neword.sql@30" -f "$W/q_payment.sql@43" -f "$W/q_ostat.sql@4" -f "$W/q_delivery.sql@25" -f "$W/q_slev.sql@4"