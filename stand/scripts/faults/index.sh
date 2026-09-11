#!/usr/bin/env bash

set -eu; source "$(dirname "$0")/lib.sh"
RUN = "${1:?укажите run_id}"

IDX = $($PSQL -c "SELECT indexrelname FROM pg_stat_all_indexes WHERE relname = 'orders' AND schemaname = 'public' AND indexrelname <> (SELECT conname FROM pg_constraint WHERE conrelid = 'public.orders'::regclass AND contype = 'p' LIMIT 1) ORDER BY pg_relation_size(indexrelid) DESC LIMIT 1;")

if [ -z "$IDX" ]; then
  echo "не найден вторичный индекс на orders"; exit 1
fi

$PSQL -c "SELECT indexdef FROM pg_indexes WHERE schemaname='public' AND indexname='$IDX';" > /tmp/pgmon_dropped_index.sql
echo "сохранено определение: $(cat /tmp/pgmon_dropped_index.sql)"

$PSQL -c "DROP INDEX public.$IDX;"

manifest "$RUN" pg_dropped_index "{\"root_causes\":[{\"entity_type\":\"index\",\"entity_id\":\"$IDX\",\"cause_class\":\"missing_index\"}],\"affected_entities\":[{\"entity_type\":\"relation\",\"entity_id\":\"public.orders\"}]}"
onset "$RUN"
echo "удалён индекс: $IDX"