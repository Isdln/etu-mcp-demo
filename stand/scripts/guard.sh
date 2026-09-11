#!/usr/bin/env bash

STAND=/opt/pgmon-stand

if [ -f "$STAND/.env" ]; then
  set -a; . "$STAND/.env"; set +a
else
  echo "ОШИБКА: нет $STAND/.env"
  exit 1
fi

check_mounts() {
  if [ ! -f /mnt/pgdata/.mounted ] || [ ! -f /mnt/pgmeta/.mounted ]; then
    echo "ОШИБКА: тома не смонтированы."
    exit 1
  fi
}

check_space() {
  local need_gb="${1:-10}"
  local free_gb
  free_gb = $(df -BG --output=avail /mnt/pgmeta | tail -1 | tr -dc '0-9')
  if [ "$free_gb" -lt "$need_gb" ]; then
    echo "ОШИБКА: на /mnt/pgmeta свободно ${free_gb} ГБ, нужно ${need_gb}."
    exit 1
  fi
}

check_instance() {
  local size roles wh
  size = $(docker exec pgmon-primary psql -U postgres -qAt -d bench -c "SELECT pg_database_size('bench')/1024/1024;" 2>/dev/null || echo 0)
  roles = $(docker exec pgmon-primary psql -U postgres -qAt -c "SELECT count(*) FROM pg_roles WHERE rolname IN ('app','replicator','pgmon_collector','pgmon_operator');" 2>/dev/null || echo 0)
  wh = $(docker exec pgmon-primary psql -U app -qAt -d bench -c "SELECT count(*) FROM warehouse;" 2>/dev/null || echo 0)

  echo "  база: ${size} МБ, ролей: ${roles}/4, складов: ${wh}"
  if [ "${size:-0}" -lt 5000 ] || [ "${roles:-0}" -lt 4 ] || [ "${wh:-0}" -lt 100 ]; then
    echo "ОШИБКА: экземпляр не в рабочем состоянии, копия не снимается."
    exit 1
  fi
}

check_replica_streaming() {
  local state
  state = $(docker exec pgmon-primary psql -U postgres -qAt -c "SELECT state FROM pg_stat_replication LIMIT 1;" 2>/dev/null || true)
  if [ "$state" != "streaming" ]; then
    echo "ОШИБКА: реплика не подключена (state='${state}')."
    exit 1
  fi
}