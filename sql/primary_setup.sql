CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
CREATE EXTENSION IF NOT EXISTS pg_wait_sampling;
CREATE EXTENSION IF NOT EXISTS pgstattuple;
CREATE EXTENSION IF NOT EXISTS pg_buffercache;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pgmon_collector') THEN CREATE ROLE pgmon_collector LOGIN PASSWORD 'change-me';
    END IF;
END
$$;

GRANT pg_monitor TO pgmon_collector;

GRANT pg_use_reserved_connections TO pgmon_collector;

ALTER ROLE pgmon_collector SET default_transaction_read_only = on;
ALTER ROLE pgmon_collector SET statement_timeout = '10s';
ALTER ROLE pgmon_collector SET idle_in_transaction_session_timeout = '15s';
ALTER ROLE pgmon_collector SET application_name = 'pgmon_collector';
ALTER ROLE pgmon_collector SET log_min_duration_statement = -1;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pgmon_operator') THEN CREATE ROLE pgmon_operator LOGIN PASSWORD 'change-me';
    END IF;
END
$$;

GRANT pg_monitor TO pgmon_operator;
GRANT pg_signal_backend TO pgmon_operator;
GRANT pg_maintain TO pgmon_operator;
ALTER ROLE pgmon_operator SET statement_timeout = '10min';
ALTER ROLE pgmon_operator SET application_name = 'pgmon_mcp_mitigation';

SELECT name, setting FROM pg_settings
WHERE name IN ('shared_preload_libraries', 'compute_query_id', 'track_io_timing', 'reserved_connections', 'log_lock_waits', 'log_destination')
ORDER BY name;