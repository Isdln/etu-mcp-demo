#!/usr/bin/env bash

set -euo pipefail
source "$(dirname "$(readlink -f "$0")")/guard.sh"
check_mounts

PSQL = "docker exec -i pgmon-primary psql -U app -d bench -qAt"

$PSQL -c "ALTER TABLE stock SET (autovacuum_vacuum_scale_factor = 0.02, autovacuum_vacuum_threshold = 10000);"

docker exec -i pgmon-primary psql -U postgres -d bench -c "VACUUM ANALYZE;" >/dev/null
docker exec -i pgmon-primary psql -U postgres -d bench -c "SELECT relname FROM pg_stat_user_tables;" -qAt | while read -r rel; do
docker exec -i pgmon-primary psql -U postgres -d bench -qAt -c "ANALYZE public.\"$rel\";" >/dev/null
done

docker exec -it pgmon-primary psql -U app -d bench -c "SELECT (SELECT count(*) FROM warehouse) AS склады, (SELECT count(*) FROM district) AS округа, (SELECT count(*) FROM customer) AS клиенты, (SELECT count(*) FROM item) AS товары;"
docker exec -it pgmon-primary psql -U app -d bench -c "SELECT relname, reloptions FROM pg_class c JOIN pg_stat_user_tables s ON s.relid = c.oid WHERE reloptions IS NOT NULL;"
docker exec -it pgmon-primary psql -U postgres -d bench -c "SELECT pg_size_pretty(pg_database_size('bench')) AS размер;"