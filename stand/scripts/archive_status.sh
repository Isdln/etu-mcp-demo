#!/usr/bin/env bash

set -eu

docker exec -it pgmon-primary psql -U postgres -qAtx -c "SELECT archived_count, last_archived_wal, last_archived_time, failed_count, last_failed_wal, last_failed_time FROM pg_stat_archiver;"

du -sh /mnt/pgmeta/archive
ls /mnt/pgmeta/archive | wc -l | xargs echo "сегментов:"
df -h /mnt/pgmeta | tail -1