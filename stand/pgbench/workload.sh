#!/usr/bin/env bash

set -u

STAND="${STAND:-/opt/pgmon-stand}"
if [ -f "$STAND/.env" ]; 
  then set -a; . "$STAND/.env"; set +a
else 
  echo "ОШИБКА: нет $STAND/.env"; exit 1;
fi

LOCK=/tmp/pgmon_workload.lock
exec 9>"$LOCK"
flock -n 9 || { echo "workload.sh уже запущен"; exit 1; }

STAND = "${STAND:-/opt/pgmon-stand}"
W = "$STAND/stand/pgbench"
LOG = "$STAND/log/workload.log"
BASE = "${PGMON_BASE_TPS:-40}"
AMPL = "${PGMON_AMPLITUDE:-20}"
SEGMIN = "${PGMON_SEGMENT_MINUTES:-5}"
CLIENTS = "${PGMON_CLIENTS:-12}"
THREADS = "${PGMON_THREADS:-2}"
HOST = "${PGMON_HOST:-127.0.0.1}"
PORT = "${PGMON_PORT:-6432}"

export PGPASSWORD="$APP_PASSWORD"

while true; do
  MIN=$(( ($(date +%s) / 60) % 60 ))
  RATE=$(python3 -c "import math;print(int($BASE + $AMPL*math.sin($MIN/60*2*math.pi)))")

  if [ $((RANDOM % 12)) -eq 0 ]; then
    RATE=$((RATE * 5 / 4))
    echo "$(date -Is) всплеск x1.25 -> $RATE транз/с" >> "$LOG"
  fi

  echo "$(date -Is) отрезок: $RATE транз/с, $SEGMIN мин, $CLIENTS клиентов" >> "$LOG"
  pgbench -h "$HOST" -p "$PORT" -U app -d bench -c "$CLIENTS" -j "$THREADS" -T $((SEGMIN * 60)) -R "$RATE" -L 5000 --random-seed=42 --progress=60  -f "$W/q_neword.sql@30"  -f "$W/q_payment.sql@43" -f "$W/q_ostat.sql@4"  -f "$W/q_delivery.sql@25" -f "$W/q_slev.sql@4"  >> "$LOG" 2>&1
done