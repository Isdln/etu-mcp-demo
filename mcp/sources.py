from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

Kind = Literal["cumulative", "instant", "event"]


@dataclass(frozen=True)
class SourceSpec:
    name: str
    kind: Kind
    relation: str = ""
    keys: tuple[str, ...] = ()
    counters: tuple[str, ...] = ()
    gauges: tuple[str, ...] = ()
    where: str = ""
    sql: str = ""
    min_pg: int = 16
    optional: bool = False

    def wishlist(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(self.keys + self.counters + self.gauges))

SOURCES: dict[str, SourceSpec] = {}

def _reg(spec: SourceSpec) -> SourceSpec:
    SOURCES[spec.name] = spec
    return spec

_reg(SourceSpec(
    name="pg_stat_statements",
    kind="cumulative",
    relation="pg_stat_statements",
    keys=("queryid", "userid", "dbid"),
    counters=("calls", "total_exec_time", "total_plan_time", "rows", "shared_blks_hit", "shared_blks_read", "shared_blks_dirtied", "shared_blks_written", "local_blks_hit", "local_blks_read",
              "temp_blks_read", "temp_blks_written", "blk_read_time", "blk_write_time", "shared_blk_read_time", "shared_blk_write_time", "temp_blk_read_time", "temp_blk_write_time", 
              "wal_records", "wal_fpi", "wal_bytes", "jit_functions", "jit_generation_time",),
    gauges=("mean_exec_time", "min_exec_time", "max_exec_time", "stddev_exec_time"),
    where="calls > 0",
    optional=True,
))

_reg(SourceSpec(
    name="pg_stat_database",
    kind="cumulative",
    relation="pg_stat_database",
    keys=("datid",),
    counters=("xact_commit", "xact_rollback", "blks_read", "blks_hit", "tup_returned", "tup_fetched", "tup_inserted", "tup_updated", "tup_deleted", "conflicts", "temp_files", "temp_bytes", 
              "deadlocks", "checksum_failures", "blk_read_time", "blk_write_time", "session_time", "active_time", "idle_in_transaction_time", "sessions", "sessions_abandoned", "sessions_fatal", 
              "sessions_killed","parallel_workers_to_launch", "parallel_workers_launched",),
    gauges=("datname", "numbackends"),
    where="datname IS NOT NULL",
))

_reg(SourceSpec(
    name="pg_stat_all_tables",
    kind="cumulative",
    relation="pg_stat_all_tables",
    keys=("relid",),
    counters=("seq_scan", "seq_tup_read", "idx_scan", "idx_tup_fetch", "n_tup_ins", "n_tup_upd", "n_tup_del", "n_tup_hot_upd", "n_tup_newpage_upd", "vacuum_count", "autovacuum_count", 
              "analyze_count", "autoanalyze_count", "total_vacuum_time", "total_autovacuum_time", "total_analyze_time", "total_autoanalyze_time",),
    gauges=("schemaname", "relname", "n_live_tup", "n_dead_tup", "n_mod_since_analyze", "n_ins_since_vacuum", "last_vacuum", "last_autovacuum", "last_analyze", "last_autoanalyze",),
    where="schemaname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')",
))

_reg(SourceSpec(
    name="pg_stat_all_indexes",
    kind="cumulative",
    relation="pg_stat_all_indexes",
    keys=("indexrelid",),
    counters=("idx_scan", "idx_tup_read", "idx_tup_fetch"),
    gauges=("schemaname", "relname", "indexrelname", "last_idx_scan"),
    where="schemaname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')",
))

_reg(SourceSpec(
    name="pg_stat_io",
    kind="cumulative",
    relation="pg_stat_io",
    keys=("backend_type", "object", "context"),
    counters=("reads", "read_time", "read_bytes", "writes", "write_time", "write_bytes", "writebacks", "writeback_time", "extends", "extend_time", "extend_bytes", "hits", "evictions", "reuses", "fsyncs", "fsync_time",),
))

_reg(SourceSpec(
    name="pg_stat_checkpointer",
    kind="cumulative",
    relation="pg_stat_checkpointer",
    keys=(),
    counters=("num_timed", "num_requested", "num_done", "restartpoints_timed", "restartpoints_req", "restartpoints_done", "write_time", "sync_time", "buffers_written", "slru_written",),
    min_pg=17,
    optional=True,
))

_reg(SourceSpec(
    name="pg_stat_bgwriter",
    kind="cumulative",
    relation="pg_stat_bgwriter",
    keys=(),
    counters=("buffers_clean", "maxwritten_clean", "buffers_alloc"),
))

_reg(SourceSpec(
    name="pg_stat_wal",
    kind="cumulative",
    relation="pg_stat_wal",
    keys=(),
    counters=("wal_records", "wal_fpi", "wal_bytes", "wal_buffers_full", "wal_write", "wal_sync", "wal_write_time", "wal_sync_time",),
))

_reg(SourceSpec(
    name="pg_stat_database_conflicts",
    kind="cumulative",
    relation="pg_stat_database_conflicts",
    keys=("datid",),
    counters=("confl_tablespace", "confl_lock", "confl_snapshot", "confl_bufferpin", "confl_deadlock", "confl_active_logicalslot",),
    gauges=("datname",),
))

_reg(SourceSpec(
    name="pg_settings",
    kind="instant",
    relation="pg_settings",
    keys=("name",),
    gauges=("setting", "unit", "source", "sourcefile", "sourceline", "boot_val", "reset_val", "pending_restart", "context", "category"),
))

_reg(SourceSpec(
    name="pg_replication_slots",
    kind="instant",
    sql="""SELECT slot_name, plugin, slot_type, database, active, active_pid, xmin::text AS xmin, catalog_xmin::text AS catalog_xmin, restart_lsn::text AS restart_lsn,
        confirmed_flush_lsn::text AS confirmed_flush_lsn, wal_status, safe_wal_size, two_phase, pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) AS retained_bytes, age(xmin) AS xmin_age, age(catalog_xmin) AS catalog_xmin_age
        FROM pg_replication_slots""",
    keys=("slot_name",),
))

_reg(SourceSpec(
    name="pg_stat_replication",
    kind="instant",
    sql="""SELECT pid, usename, application_name, client_addr::text AS client_addr, state, sync_state, sent_lsn::text AS sent_lsn, replay_lsn::text AS replay_lsn,
        EXTRACT(epoch FROM write_lag)  AS write_lag_s, EXTRACT(epoch FROM flush_lag)  AS flush_lag_s, EXTRACT(epoch FROM replay_lag) AS replay_lag_s, pg_wal_lsn_diff(sent_lsn, replay_lsn) AS replay_lag_bytes
        FROM pg_stat_replication""",
    keys=("pid",),
))

_reg(SourceSpec(
    name="pg_prepared_xacts",
    kind="instant",
    sql="SELECT gid, prepared, owner, database,EXTRACT(epoch FROM now() - prepared) AS age_s, age(transaction) AS xid_age FROM pg_prepared_xacts",
    keys=("gid",),
))

_reg(SourceSpec(
    name="relation_state",
    kind="instant",
    sql="""SELECT c.oid AS relid, n.nspname AS schemaname, c.relname, c.relkind, pg_total_relation_size(c.oid) AS total_bytes, pg_relation_size(c.oid) AS heap_bytes,
        pg_indexes_size(c.oid) AS index_bytes, c.reltuples, c.relpages, age(c.relfrozenxid) AS frozenxid_age, mxid_age(c.relminmxid) AS minmxid_age, c.reloptions::text AS reloptions
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind IN ('r', 'm', 'p') AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')""",
    keys=("relid",),
))

_reg(SourceSpec(
    name="index_state",
    kind="instant",
    sql="""SELECT i.indexrelid, n.nspname AS schemaname, t.relname, ic.relname AS indexrelname, i.indisvalid, i.indisready, i.indisunique, i.indisprimary, pg_relation_size(i.indexrelid) AS index_bytes, pg_get_indexdef(i.indexrelid)  AS indexdef
        FROM pg_index i
        JOIN pg_class ic ON ic.oid = i.indexrelid
        JOIN pg_class t  ON t.oid  = i.indrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')""",
    keys=("indexrelid",),
))

_reg(SourceSpec(
    name="pg_stat_progress_vacuum",
    kind="instant",
    relation="pg_stat_progress_vacuum",
    keys=("pid",),
    gauges=("datname", "relid", "phase", "heap_blks_total", "heap_blks_scanned", "heap_blks_vacuumed", "index_vacuum_count", "max_dead_tuple_bytes", "dead_tuple_bytes", "num_dead_item_ids"),
))

_reg(SourceSpec(
    name="db_role_setting",
    kind="instant",
    sql="""SELECT COALESCE(d.datname, '<all>') AS datname, COALESCE(r.rolname, '<all>') AS rolname, s.setconfig::text AS setconfig
        FROM pg_db_role_setting s
        LEFT JOIN pg_database d ON d.oid = s.setdatabase
        LEFT JOIN pg_roles    r ON r.oid = s.setrole""",
    keys=("datname", "rolname"),
))

ASH_SQL="""SELECT now() AS sampled_at, pid, datname, usename, application_name, client_addr::text AS client_addr, backend_type, state, COALESCE(wait_event_type, 'CPU') AS wait_event_type,
        COALESCE(wait_event, 'CPU') AS wait_event, query_id AS queryid, backend_xmin::text AS backend_xmin, EXTRACT(epoch FROM now() - xact_start) AS xact_age_s, EXTRACT(epoch FROM now() - query_start) AS query_age_s,
        EXTRACT(epoch FROM now() - state_change) AS state_age_s, left(query, 400) AS query_sample
        FROM pg_stat_activity
        WHERE pid <> pg_backend_pid() AND COALESCE(application_name, '') <> %(self_app)s AND (state <> 'idle' OR backend_xmin IS NOT NULL OR xact_start IS NOT NULL)"""

LOCK_GRAPH_SQL="""SELECT now() AS sampled_at, w.pid AS blocked_pid, b AS blocking_pid, w.usename AS blocked_user, w.application_name AS blocked_app, w.wait_event_type, w.wait_event,
                EXTRACT(epoch FROM now() - w.state_change) AS waiting_s, left(w.query, 300) AS blocked_query, l.locktype, l.mode, l.relation::regclass::text AS relation
                FROM pg_stat_activity w
                CROSS JOIN LATERAL unnest(pg_blocking_pids(w.pid)) AS b
                LEFT JOIN pg_locks l ON l.pid = w.pid AND NOT l.granted
                WHERE cardinality(pg_blocking_pids(w.pid)) > 0 AND COALESCE(w.application_name, '') <> %(self_app)s"""

def num(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    
    try:
        return float(value)
    
    except (TypeError, ValueError):
        return default


def row_key(spec: SourceSpec, row: dict[str, Any]) -> tuple:
    if not spec.keys:
        return ("__singleton__",)
    
    return tuple(str(row.get(k)) for k in spec.keys)


def compute_delta(spec: SourceSpec, first: Iterable[dict[str, Any]] | None, last: Iterable[dict[str, Any]] | None,) -> tuple[list[dict[str, Any]], bool]:
    first_rows = list(first or [])
    last_rows = list(last or [])
    base = {row_key(spec, r): r for r in first_rows}

    out: list[dict[str, Any]] = []
    reset_detected = False

    for row in last_rows:
        key = row_key(spec, row)
        prev = base.get(key)
        result: dict[str, Any] = {k: row.get(k) for k in spec.keys}
        for col in spec.counters:
            if col not in row or row[col] is None:
                continue
            
            cur = num(row[col])

            if prev is None or prev.get(col) is None:
                result[f"d_{col}"] = cur
                continue
            
            before = num(prev[col])

            if cur < before:
                reset_detected = True
                result[f"d_{col}"] = cur

            else:
                result[f"d_{col}"] = cur - before

        for col in spec.gauges:
            if col in row:
                result[col] = row[col]

        result["_first_seen_in_window"] = prev is None
        out.append(result)

    return out, reset_detected

def as_rate(value: float | None, seconds: float) -> float | None:
    if value is None or seconds <= 0:
        return None
    
    return round(value / seconds, 4)