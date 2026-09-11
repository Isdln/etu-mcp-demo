CREATE SCHEMA IF NOT EXISTS pgmon;

CREATE TABLE IF NOT EXISTS pgmon.sample (
    sample_id bigserial PRIMARY KEY,
    run_id text NOT NULL,
    source text NOT NULL,
    taken_at timestamptz NOT NULL,
    payload jsonb NOT NULL
);

CREATE INDEX IF NOT EXISTS sample_lookup ON pgmon.sample (run_id, source, taken_at);

CREATE TABLE IF NOT EXISTS pgmon.event (
    event_id bigserial PRIMARY KEY,
    run_id text NOT NULL,
    kind text NOT NULL,
    sampled_at timestamptz NOT NULL,
    payload jsonb NOT NULL
);

CREATE INDEX IF NOT EXISTS event_lookup ON pgmon.event (run_id, kind, sampled_at);

CREATE TABLE IF NOT EXISTS pgmon.run (
    run_id text PRIMARY KEY,
    scenario_id text,
    difficulty text,
    started_at timestamptz NOT NULL DEFAULT now(),
    inject_at timestamptz,
    symptom_onset timestamptz,
    window_from timestamptz,
    window_to timestamptz,
    ground_truth jsonb
);

COMMENT ON COLUMN pgmon.run.symptom_onset IS 'Момент появления симптома, а не инжекции. Для отказов класса bloat разрыв достигает десятков минут, и время детекции надо считать именно отсюда, иначе метрика TTD бессмысленна.';

CREATE OR REPLACE FUNCTION pgmon.purge_run(p_run_id text)
RETURNS void LANGUAGE sql AS $$
    DELETE FROM pgmon.event WHERE run_id = p_run_id;
    DELETE FROM pgmon.sample WHERE run_id = p_run_id;
    DELETE FROM pgmon.run WHERE run_id = p_run_id;
$$;