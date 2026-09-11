#!/usr/bin/env bash

set -u

STAND = "${STAND:-/opt/pgmon-stand}"

if 
  [ -f "$STAND/.env" ]; then set -a; . "$STAND/.env"; set +a
else 
  echo "ОШИБКА: нет $STAND/.env"; exit 1; 
fi

RUN_ID = "${1:?укажите идентификатор прогона}"
STAND = /opt/pgmon-stand

source "$(dirname "$(readlink -f "$0")")/guard.sh"
check_mounts
check_space 8
exec "$STAND/venv/bin/pgmon-collector" --target-dsn "postgresql://pgmon_collector:$COLLECTOR_PASSWORD@127.0.0.1:5432/bench" --meta-dsn "postgresql://postgres:$META_PASSWORD@127.0.0.1:5433/pgmon_meta" --run-id "$RUN_ID" --log-file "$STAND/log/primary/postgresql.csv" --pgbouncer-dsn "postgresql://app:$APP_PASSWORD@127.0.0.1:6432/pgbouncer" --collect-host --snapshot-interval 30 --instant-interval 5 --ash-interval 1