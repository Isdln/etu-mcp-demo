#!/usr/bin/env bash

set -euo pipefail
source "$(dirname "$(readlink -f "$0")")/guard.sh"
cd /opt/pgmon-stand

check_mounts
check_space 12
check_instance
check_replica_streaming

OPTS = $(docker exec pgmon-primary psql -U app -qAt -d bench -c "SELECT coalesce(reloptions::text,'') FROM pg_class WHERE relname='stock';" 2>/dev/null || true)
if [[ "$OPTS" != *autovacuum_vacuum_scale_factor* ]]; then
  echo "ОШИБКА: на stock нет настроек автоочистки."
  exit 1
fi

sudo rm -rf /mnt/pgmeta/snapshots/base
docker exec pgmon-primary pg_basebackup -U postgres -D /var/lib/postgresql/snapshots/base --format=tar --compress=zstd:3 --checkpoint=fast --progress --wal-method=stream

sudo chown -R "$USER:$USER" /mnt/pgmeta/snapshots/base
[ -f /mnt/pgmeta/snapshots/base/pg_wal.tar ] && zstd -3 -q --rm /mnt/pgmeta/snapshots/base/pg_wal.tar

SIZE = $(stat -c%s /mnt/pgmeta/snapshots/base/base.tar.zst)

if [ "$SIZE" -lt 1000000000 ]; then
  echo "ОШИБКА: копия всего $((SIZE/1024/1024)) МБ, ожидалось около 5 ГБ."
  exit 1
fi

zstd -t /mnt/pgmeta/snapshots/base/base.tar.zst
zstd -t /mnt/pgmeta/snapshots/base/pg_wal.tar.zst
ls -lh --time-style=+%H:%M /mnt/pgmeta/snapshots/base/