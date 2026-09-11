#!/usr/bin/env bash

STAND = "${STAND:-/opt/pgmon-stand}"
if [ -f "$STAND/.env" ]; 
  then set -a; . "$STAND/.env"; set +a
else echo "ОШИБКА: нет $STAND/.env"; exit 1; 
fi

PSQL = "docker exec -i pgmon-primary psql -U postgres -d bench -qAt"
META = "docker exec -i pgmon-meta psql -U postgres -d pgmon_meta -qAt"

manifest() {
  local run="$1" scenario="$2" difficulty="$3" gt="$4"
  $META <<SQL
INSERT INTO pgmon.run (run_id, scenario_id, difficulty, inject_at, ground_truth)
VALUES ('$run', '$scenario', '$difficulty', now(), '$gt'::jsonb)
ON CONFLICT (run_id) DO UPDATE SET scenario_id = EXCLUDED.scenario_id, difficulty  = EXCLUDED.difficulty, ground_truth= EXCLUDED.ground_truth;
SQL

  echo "манифест записан: $scenario ($difficulty)"
}

onset() {
  $META -c "UPDATE pgmon.run SET symptom_onset = now() WHERE run_id = '$1';"
  echo "момент появления симптома зафиксирован"
}
