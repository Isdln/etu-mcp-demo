#!/usr/bin/env bash

set -eu; source "$(dirname "$0")/lib.sh"

RUN = "${1:?укажите run_id}"

docker exec -d pgmon-primary psql -U postgres -d bench -c "BEGIN; LOCK TABLE district IN ACCESS EXCLUSIVE MODE; SELECT pg_sleep(1800);"

sleep 2

PID = $($PSQL -c "SELECT pid FROM pg_stat_activity WHERE query LIKE '%ACCESS EXCLUSIVE%' AND state<>'idle' LIMIT 1;")
manifest "$RUN" pg_lock_queue_004 L2 "{\"root_causes\":[{\"entity_type\":\"session\",\"entity_id\":\"$PID\",\"cause_class\":\"lock_contention\"}],\"affected_entities\":[{\"entity_type\":\"relation\",\"entity_id\":\"public.district\"}]}"
onset "$RUN"

echo "блокирующая сессия: pid=$PID"