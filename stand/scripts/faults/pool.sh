#!/usr/bin/env bash

set -eu; source "$(dirname "$0")/lib.sh"
RUN = "${1:?укажите run_id}"

sudo sed -i 's/^default_pool_size = .*/default_pool_size = 3/' /opt/pgmon-stand/stand/conf/pgbouncer.ini

docker kill -s HUP pgmon-pgbouncer
manifest "$RUN" pg_pool_exhaustion '{"root_causes":[{"entity_type":"connection_pool","entity_id":"bench","cause_class":"pool_exhaustion"}],"affected_entities":[]}'
onset "$RUN"