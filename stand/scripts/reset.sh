#!/usr/bin/env bash

set -euo pipefail
source "$(dirname "$(readlink -f "$0")")/guard.sh"
cd /opt/pgmon-stand
BASE = /mnt/pgmeta/snapshots/base

check_mounts
[ -f "$BASE/base.tar.zst" ] || { echo "нет базовой копии, выполните snapshot.sh"; exit 1; }

docker compose stop primary replica
docker rm -f pgmon-clone 2>/dev/null || true

sudo rm -rf /mnt/pgdata/primary
sudo mkdir -p /mnt/pgdata/primary/pgdata
sudo tar -I zstd -xf "$BASE/base.tar.zst"   -C /mnt/pgdata/primary/pgdata
sudo tar -I zstd -xf "$BASE/pg_wal.tar.zst" -C /mnt/pgdata/primary/pgdata/pg_wal
sudo chown -R 999:999 /mnt/pgdata/primary
sudo chmod 700 /mnt/pgdata/primary /mnt/pgdata/primary/pgdata

sudo find /mnt/pgmeta/archive -type f -delete

docker compose start primary
for i in $(seq 1 30); do
  docker exec pgmon-primary pg_isready -U postgres -q 2>/dev/null && break
  sleep 2
done
docker exec pgmon-primary pg_isready -U postgres

sudo rm -rf /mnt/pgdata/replica
sudo mkdir -p /mnt/pgdata/replica
sudo chown 999:999 /mnt/pgdata/replica && sudo chmod 700 /mnt/pgdata/replica

docker exec pgmon-primary psql -U postgres -qAt -c "SELECT pg_drop_replication_slot('replica_main') WHERE EXISTS (SELECT 1 FROM pg_replication_slots WHERE slot_name='replica_main');" >/dev/null 2>&1 || true

docker run --rm --network pgmon-stand_stand -v /mnt/pgdata/replica:/target -e PGPASSWORD="$REPLICATOR_PASSWORD" pgmon/postgres:18 pg_basebackup -h primary -U replicator -D /target/pgdata -X stream -C -S replica_main -R --checkpoint=fast

sudo chown -R 999:999 /mnt/pgdata/replica && sudo chmod 700 /mnt/pgdata/replica
docker compose start replica

for i in $(seq 1 20); do
  STATE = $(docker exec pgmon-primary psql -U postgres -qAt -c "SELECT state FROM pg_stat_replication LIMIT 1;" 2>/dev/null || true)
  [ "$STATE" = "streaming" ] && break
  sleep 3
done

docker exec pgmon-primary psql -U postgres -c "SELECT application_name, state FROM pg_stat_replication;"
docker exec pgmon-primary psql -U postgres -d bench -c "SELECT pg_size_pretty(pg_database_size('bench')) AS size;"
docker exec pgmon-primary psql -U app -d bench -c "SELECT count(*) AS warehouses FROM warehouse;"