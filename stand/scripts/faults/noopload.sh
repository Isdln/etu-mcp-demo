#!/usr/bin/env bash

set -eu; source "$(dirname "$0")/lib.sh"
RUN = "${1:?укажите run_id}"
export PGMON_BASE_TPS=55

manifest "$RUN" pg_benign_load noop '{"root_causes":[], "affected_entities":[]}'
onset "$RUN"
echo "перезапустите workload.sh с PGMON_BASE_TPS=55"