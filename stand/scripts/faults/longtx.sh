#!/usr/bin/env bash

set -eu; source "$(dirname "$0")/lib.sh"
RUN = "${1:?укажите run_id}"
STAND = /opt/pgmon-stand
HOLD_SECONDS = "${PGMON_HOLD_SECONDS:-10800}"

PGPASSWORD = "$PG_SUPERUSER_PASSWORD" nohup psql -h 127.0.0.1 -p 5432 -U postgres -d bench -c "BEGIN ISOLATION LEVEL REPEATABLE READ; SELECT count(*) FROM warehouse; SELECT pg_sleep($HOLD_SECONDS);" > "$STAND/log/longtx.log" 2>&1 &

sleep 5
PID=$($PSQL -c "SELECT pid FROM pg_stat_activity WHERE backend_xmin IS NOT NULL AND query LIKE '%pg_sleep($HOLD_SECONDS)%' AND pid <> pg_backend_pid() ORDER BY xact_start LIMIT 1;")

if [ -z "$PID" ]; then
  echo "ОШИБКА: транзакция не найдена. Проверьте:"
  echo "  cat $STAND/log/longtx.log"
  echo "  docker exec -it pgmon-primary psql -U postgres -c \"SHOW idle_in_transaction_session_timeout;\""
  exit 1
fi

manifest "$RUN" pg_longtx "{\"root_causes\":[{\"entity_type\":\"session\",\"entity_id\":\"$PID\",\"cause_class\":\"xmin_horizon_block\"}],\"affected_entities\":[{\"entity_type\":\"relation\",\"entity_id\":\"public.order_line\"},{\"entity_type\":\"relation\",\"entity_id\":\"public.stock\"},{\"entity_type\":\"relation\",\"entity_id\":\"public.warehouse\"}]}"

echo "держатель: pid=$PID"
$PSQL -c "SELECT pid, state, backend_xmin, age(backend_xmin) AS xmin_age,round(extract(epoch FROM now()-xact_start)) AS xact_age_s FROM pg_stat_activity WHERE pid = $PID;"