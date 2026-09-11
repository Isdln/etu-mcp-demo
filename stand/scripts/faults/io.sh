#!/usr/bin/env bash

set -eu; source "$(dirname "$0")/lib.sh"

RUN = "${1:?укажите run_id}"

CID = $(docker inspect -f '{{.Id}}' pgmon-primary)
CG = /sys/fs/cgroup/system.slice/docker-$CID.scope
[ -d "$CG" ] || CG=$(find /sys/fs/cgroup -name "*$CID*" -type d | head -1)
DEV = $(lsblk -no MAJ:MIN /dev/sdb | head -1)
echo "$DEV rbps=16777216 wbps=8388608" | sudo tee "$CG/io.max"

manifest "$RUN" pg_io '{"root_causes":[{"entity_type":"host_resource","entity_id":"pgdata_device", "cause_class":"resource_throttle"}],\ "affected_entities":[]}'
onset "$RUN"
echo "установлено чтение 16 МБ/с, запись 8 МБ/с"