#!/usr/bin/env bash

set -u
PSQL = "docker exec -i pgmon-primary psql -U postgres -d bench -qAt"

pkill -f "pg_sleep(10800)" 2>/dev/null || true
$PSQL -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE query LIKE '%pg_sleep(%' AND pid <> pg_backend_pid();" 2>/dev/null || true

if [ -s /tmp/pgmon_dropped_index.sql ]; then
  $PSQL -f /tmp/pgmon_dropped_index.sql 2>/dev/null && rm -f /tmp/pgmon_dropped_index.sql
fi

$PSQL -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE query LIKE '%ACCESS EXCLUSIVE%' AND pid <> pg_backend_pid();" 2>/dev/null || true
CID = $(docker inspect -f '{{.Id}}' pgmon-primary 2>/dev/null || true)

if [ -n "$CID" ]; then
  CG = $(find /sys/fs/cgroup -name "*$CID*" -type d 2>/dev/null | head -1)
  DEV = $(lsblk -no MAJ:MIN /dev/sdb | head -1)
  [ -n "$CG" ] && echo "$DEV rbps=max wbps=max" | sudo tee "$CG/io.max" >/dev/null
fi

sudo sed -i 's/^default_pool_size = .*/default_pool_size = 30/' /opt/pgmon-stand/stand/conf/pgbouncer.ini 2>/dev/null || true

docker kill -s HUP pgmon-pgbouncer 2>/dev/null || true