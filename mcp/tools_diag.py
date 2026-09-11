from __future__ import annotations
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any
from .aliases import load_aliases
from .backends import Backend
from .config import Config
from .sources import as_rate, num
from .util import baseline_window, envelope, log_template, parse_window, ratio, _iso

def _at(cfg: Config, ref: datetime, at: str | None) -> datetime:
    return _iso(at) or ref

async def wait_profile(cfg: Config, backend: Backend, window: dict[str, str] | None = None, group_by: str = "wait_event", limit: int = 20,) -> dict[str, Any]:
    allowed = {"wait_event", "wait_event_type", "query", "backend_type", "state", "time"}

    if group_by not in allowed:
        return {"error": f"group_by должен быть одним из {sorted(allowed)}"}

    ref = await backend.reference_time()
    w = parse_window(cfg, ref, window)
    rows = await backend.events("ash", w.start, w.end)

    if not rows:
        return {"error": "нет данных ASH за окно", "hint": "the source may be disabled by the ablation profile", "window": w.as_dict()}

    aliases = await load_aliases(backend, w.end)
    ticks = sorted({r["sampled_at"] for r in rows})
    n_ticks = len(ticks) or 1

    if group_by == "time":
        by_bucket: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for r in rows:
            if r.get("state") != "active":
                continue
            
            by_bucket[r["sampled_at"][:16]][r.get("wait_event_type") or "CPU"] += 1
        out = [{"minute": k, "avg_active_sessions": round(sum(v.values()) / 60, 2), **v} for k, v in sorted(by_bucket.items())]

        return envelope(out, budget=cfg.budget, ordered_by="minute", window=w, limit=limit)

    counts: dict[Any, int] = defaultdict(int)
    for r in rows:
        if r.get("state") != "active":
            continue
        
        if group_by == "wait_event":
            key = f"{r.get('wait_event_type') or 'CPU'}:{r.get('wait_event') or 'CPU'}"

        elif group_by == "query":
            key = aliases.alias(r.get("queryid"))

        else:
            key = r.get(group_by) or "?"

        counts[key] += 1

    total = sum(counts.values()) or 1
    out = [{group_by: k, "samples": v, "share": round(v / total, 4), "avg_active_sessions": round(v / n_ticks, 3),} for k, v in sorted(counts.items(), key=lambda kv: -kv[1])]

    b = baseline_window(cfg, w) if cfg.ablation.baseline else None

    if b:
        base_rows = await backend.events("ash", b.start, b.end)
        base_ticks = len({r["sampled_at"] for r in base_rows}) or 1
        base_counts: dict[Any, int] = defaultdict(int)
        for r in base_rows:
            if r.get("state") != "active":
                continue
            
            if group_by == "wait_event":
                k = f"{r.get('wait_event_type') or 'CPU'}:{r.get('wait_event') or 'CPU'}"

            elif group_by == "query":
                k = aliases.alias(r.get("queryid"))

            else:
                k = r.get(group_by) or "?"

            base_counts[k] += 1

        for item in out:
            base_aas = base_counts.get(item[group_by], 0) / base_ticks
            item["baseline_avg_active_sessions"] = round(base_aas, 3)
            item["ratio"] = ratio(item["avg_active_sessions"], base_aas or None)

    return envelope(out, budget=cfg.budget, ordered_by="samples", window=w, baseline=b, limit=limit,
        extra={"ash_ticks": n_ticks, "sampling_hint": "avg_active_sessions is the average number of active sessions in this state; the sum across all rows ≈ the average database load"},)

async def sessions(cfg: Config, backend: Backend, at: str | None = None, state: str | None = None, min_age_s: float = 0.0, limit: int = 20,) -> dict[str, Any]:
    ref = await backend.reference_time()
    moment = _at(cfg, ref, at)
    rows = await backend.events("ash", moment - timedelta(seconds=10), moment)

    if not rows:
        return {"error": "нет семплов ASH около указанного момента", "at": moment.isoformat()}

    latest = max(r["sampled_at"] for r in rows)
    snap = [r for r in rows if r["sampled_at"] == latest]
    aliases = await load_aliases(backend, moment)

    out = []
    for r in snap:
        if state and r.get("state") != state:
            continue
        
        age = num(r.get("xact_age_s"))

        if age < min_age_s:
            continue
        
        out.append({"pid": r.get("pid"), "state": r.get("state"), "wait": f"{r.get('wait_event_type')}:{r.get('wait_event')}", "user": r.get("usename"), "application": r.get("application_name"),
                    "query": aliases.alias(r.get("queryid")), "xact_age_s": round(age, 1), "query_age_s": round(num(r.get("query_age_s")), 1), "state_age_s": round(num(r.get("state_age_s")), 1),
                    "backend_xmin": r.get("backend_xmin"), "query_sample": r.get("query_sample"),})

    out.sort(key=lambda x: x["xact_age_s"], reverse=True)

    return envelope(out, budget=cfg.budget, ordered_by="xact_age_s", limit=limit, extra={"at": latest})

async def lock_graph( cfg: Config, backend: Backend, window: dict[str, str] | None = None, limit: int = 20,) -> dict[str, Any]:
    ref = await backend.reference_time()
    w = parse_window(cfg, ref, window)
    rows = await backend.events("locks", w.start, w.end)

    if not rows:
        return {"rows": [], "shown": 0, "total_rows": 0, "truncated": False, "ordered_by": "-", "window": w.as_dict(), "note": "блокировок с ожиданием в окне не зафиксировано"}

    edges: dict[tuple[int, int], dict[str, Any]] = {}
    blocked_by: dict[int, set[int]] = defaultdict(set)

    for r in rows:
        key = (r["blocked_pid"], r["blocking_pid"])
        agg = edges.setdefault(key, {"blocked_pid": r["blocked_pid"], "blocking_pid": r["blocking_pid"], "relation": r.get("relation"), "lock_mode": r.get("mode"), "locktype": r.get("locktype"),
                                     "blocked_query": r.get("blocked_query"), "samples": 0, "max_waiting_s": 0.0,})
        agg["samples"] += 1
        agg["max_waiting_s"] = max(agg["max_waiting_s"], num(r.get("waiting_s")))
        blocked_by[r["blocked_pid"]].add(r["blocking_pid"])

    all_blocked = set(blocked_by)
    all_blockers = {b for s in blocked_by.values() for b in s}
    roots = sorted(all_blockers - all_blocked)

    def depth(pid: int, seen: frozenset[int] = frozenset()) -> int:
        if pid in seen:
            return 0
        
        children = [p for p, bs in blocked_by.items() if pid in bs]

        return 1 + max((depth(c, seen | {pid}) for c in children), default=0)

    out = sorted(edges.values(), key=lambda e: -e["max_waiting_s"])
    return envelope(out, budget=cfg.budget, ordered_by="max_waiting_s", window=w, limit=limit, extra={"root_blockers": [ {"pid": p, "chain_depth": depth(p), 
                                                                                                                          "blocks_directly": sum(1 for bs in blocked_by.values() if p in bs)} for p in roots], 
                                                                                                    "hint": "the root of the chain (root_blockers) is a candidate root cause; check session details via sessions(at=...)",},)

async def table_health( cfg: Config, backend: Backend, relation: str | None = None, window: dict[str, str] | None = None, order_by: str = "dead_ratio", limit: int = 15,) -> dict[str, Any]:
    ref = await backend.reference_time()
    w = parse_window(cfg, ref, window)
    stat_rows, meta = await backend.delta("pg_stat_all_tables", w.start, w.end)
    state = await backend.snapshot_at("relation_state", w.end)
    by_relid = {str(r.get("relid")): r for r in state}
    out = []

    for r in stat_rows:
        name = f"{r.get('schemaname')}.{r.get('relname')}"

        if relation and relation not in (name, r.get("relname")):
            continue
        
        st = by_relid.get(str(r.get("relid")), {})
        live = num(r.get("n_live_tup"))
        dead = num(r.get("n_dead_tup"))
        out.append({"relation": name, "live_tuples": live, "dead_tuples": dead, "dead_ratio": round(dead / (live + dead), 4) if (live + dead) else 0, "mod_since_analyze": r.get("n_mod_since_analyze"),
                    "total_bytes": st.get("total_bytes"), "heap_bytes": st.get("heap_bytes"), "index_bytes": st.get("index_bytes"), "frozenxid_age": st.get("frozenxid_age"),
                    "reloptions": st.get("reloptions"), "last_vacuum": r.get("last_vacuum"), "last_autovacuum": r.get("last_autovacuum"), "last_analyze": r.get("last_analyze"),
                    "last_autoanalyze": r.get("last_autoanalyze"), "d_seq_scan": r.get("d_seq_scan"), "d_idx_scan": r.get("d_idx_scan"), "d_seq_tup_read": r.get("d_seq_tup_read"), 
                    "d_n_tup_upd": r.get("d_n_tup_upd"), "d_n_tup_hot_upd": r.get("d_n_tup_hot_upd"), "d_autovacuum_count": r.get("d_autovacuum_count"), "d_autoanalyze_count": r.get("d_autoanalyze_count"),})

    keys = {"dead_ratio": "dead_ratio", "seq_scan": "d_seq_scan", "size": "total_bytes", "frozenxid_age": "frozenxid_age", "updates": "d_n_tup_upd",}
    out.sort(key=lambda x: num(x.get(keys.get(order_by, "dead_ratio"))), reverse=True)
    notes = []

    if any((r.get("reloptions") or "").find("autovacuum_enabled=false") >= 0 for r in out):
        notes.append("у части таблиц автовакуум выключен через reloptions")

    return envelope(out, budget=cfg.budget, ordered_by=order_by, window=w, limit=limit, notes=notes, extra={"delta_meta": meta})

async def index_health(window: dict[str, str] | None = None, limit: int = 20,) -> dict[str, Any]:
    ref = await backend.reference_time()
    w = parse_window(cfg, ref, window)
    stat_rows, meta = await backend.delta("pg_stat_all_indexes", w.start, w.end)
    state = {str(r.get("indexrelid")): r for r in await backend.snapshot_at("index_state", w.end)}

    b = baseline_window(cfg, w) if cfg.ablation.baseline else None
    base = {}

    if b:
        base_rows, _ = await backend.delta("pg_stat_all_indexes", b.start, b.end)
        base = {str(r.get("indexrelid")): r for r in base_rows}

    out = []
    for r in stat_rows:
        table = f"{r.get('schemaname')}.{r.get('relname')}"

        if relation and relation not in (table, r.get("relname")):
            continue
        
        st = state.get(str(r.get("indexrelid")), {})
        scans = num(r.get("d_idx_scan"))
        prev = (base.get(str(r.get("indexrelid"))) or {}).get("d_idx_scan")
        out.append({"index": r.get("indexrelname"), "table": table, "d_idx_scan": scans, "baseline_idx_scan": prev, "scan_ratio": ratio(scans, prev), "size_bytes": st.get("index_bytes"),
                    "valid": st.get("indisvalid"), "ready": st.get("indisready"), "unique": st.get("indisunique"), "primary": st.get("indisprimary"), "definition": st.get("indexdef"), "unused_in_window": scans == 0,})
    out.sort(key=lambda x: (x["scan_ratio"] is not None and x["scan_ratio"] < 0.5,
                            -num(x.get("size_bytes"))))

    notes = []

    if any(r["valid"] is False for r in out):
        notes.append("есть невалидные индексы (indisvalid=false) это признак прерванного CREATE INDEX CONCURRENTLY")

    if any(r["baseline_idx_scan"] and r["d_idx_scan"] == 0 for r in out):
        notes.append("часть индексов перестала использоваться по сравнению с эталонным окном, вероятна смена плана или DROP INDEX")

    return envelope(out, budget=cfg.budget, ordered_by="подозрительность", window=w, baseline=b, limit=limit, notes=notes, extra={"delta_meta": meta})

async def schema_object(cfg: Config, backend: Backend, relation: str) -> dict[str, Any]:
    ref = await backend.reference_time()
    tables = await backend.snapshot_at("relation_state", ref)
    match = next( (r for r in tables if f"{r.get('schemaname')}.{r.get('relname')}" == relation or r.get("relname") == relation), None,)

    if not match:
        return {"error": f"отношение {relation!r} не найдено в снимке каталога"}
    
    idx = [r for r in await backend.snapshot_at("index_state", ref) if f"{r.get('schemaname')}.{r.get('relname')}" == f"{match['schemaname']}.{match['relname']}"]

    return {"relation": f"{match['schemaname']}.{match['relname']}", "kind": match.get("relkind"), "reltuples": match.get("reltuples"), "relpages": match.get("relpages"), 
            "total_bytes": match.get("total_bytes"), "reloptions": match.get("reloptions"), "frozenxid_age": match.get("frozenxid_age"),
            "indexes": [{"name": i.get("indexrelname"), "definition": i.get("indexdef"), "valid": i.get("indisvalid"), "size_bytes": i.get("index_bytes")} for i in idx],}

async def xmin_horizon(cfg: Config, backend: Backend, at: str | None = None) -> dict[str, Any]:
    ref = await backend.reference_time()
    moment = _at(cfg, ref, at)

    slots = await backend.snapshot_at("pg_replication_slots", moment)
    prepared = await backend.snapshot_at("pg_prepared_xacts", moment)
    settings = {r["name"]: r for r in await backend.snapshot_at("pg_settings", moment)}
    ash = await backend.events("ash", moment - timedelta(seconds=60), moment)

    holders: list[dict[str, Any]] = []
    for s in slots:
        if s.get("xmin") or s.get("catalog_xmin"):
            holders.append({ "kind": "replication_slot", "id": s.get("slot_name"), "active": s.get("active"), "xmin_age": s.get("xmin_age"), "catalog_xmin_age": s.get("catalog_xmin_age"), 
                            "retained_wal_bytes": s.get("retained_bytes"), "wal_status": s.get("wal_status"), "severity": "high" if not s.get("active") else "medium",})

    for p in prepared:
        holders.append({"kind": "prepared_transaction", "id": p.get("gid"), "age_s": round(num(p.get("age_s")), 1), "xid_age": p.get("xid_age"), "severity": "high",})

    if ash:
        latest = max(r["sampled_at"] for r in ash)
        for r in [x for x in ash if x["sampled_at"] == latest]:
            age = num(r.get("xact_age_s"))
            if r.get("backend_xmin") and age > 60:
                holders.append({"kind": "session", "id": r.get("pid"), "state": r.get("state"), "application": r.get("application_name"), "xact_age_s": round(age, 1), 
                                "backend_xmin": r.get("backend_xmin"), "severity": "high" if (age > 600 or r.get("state") == "idle in transaction") else "medium",})

    holders.sort(key=lambda h: {"high": 0, "medium": 1}.get(h.get("severity"), 2))

    return {"at": moment.isoformat(), "holders": holders, "holder_count": len(holders), "hot_standby_feedback": (settings.get("hot_standby_feedback") or {}).get("setting"), 
            "old_snapshot_threshold": (settings.get("old_snapshot_threshold") or {}).get("setting"), "hint": "if holders are present, autovacuum will run normally, but dead tuples will remain so check against table_health.dead_ratio",}

async def maintenance_status(cfg: Config, backend: Backend, window: dict[str, str] | None = None, limit: int = 20,) -> dict[str, Any]:
    ref = await backend.reference_time()
    w = parse_window(cfg, ref, window)
    points = await backend.series("pg_stat_progress_vacuum", w.start, w.end, 30)
    running = []

    for ts, payload in points:
        for r in payload:
            total = num(r.get("heap_blks_total"))
            running.append({"at": ts.isoformat(), "pid": r.get("pid"), "relid": r.get("relid"), "phase": r.get("phase"), "progress": round(num(r.get("heap_blks_scanned")) / total, 3) 
                            if total else None, "index_vacuum_count": r.get("index_vacuum_count"),})

    logs = await backend.events("pg_log", w.start, w.end)
    autovac = [l for l in logs if "automatic vacuum" in (l.get("message") or "") or "automatic analyze" in (l.get("message") or "")]

    return envelope(running, budget=cfg.budget, ordered_by="at", window=w, limit=limit, extra={"autovacuum_log_entries": len(autovac), "recent_autovacuum": [{"at": l.get("ts"), "message": l.get("message")} for l in autovac[-5:]],},)

async def pool_status(cfg: Config, backend: Backend, window: dict[str, str] | None = None) -> dict[str, Any]:
    ref = await backend.reference_time()
    w = parse_window(cfg, ref, window)
    points = await backend.series("pgbouncer_pools", w.start, w.end, 40)

    if not points:
        return {"error": "нет данных PgBouncer за окно", "window": w.as_dict()}

    series = []
    for ts, payload in points:
        series.append({"at": ts.isoformat(), "cl_active": sum(num(r.get("cl_active")) for r in payload), "cl_waiting": sum(num(r.get("cl_waiting")) for r in payload), "sv_active": sum(num(r.get("sv_active")) for r in payload),
                       "sv_idle": sum(num(r.get("sv_idle")) for r in payload), "maxwait_s": max(num(r.get("maxwait")) for r in payload),})

    peak = max(series, key=lambda x: x["cl_waiting"])

    return {"window": w.as_dict(), "series": series[-cfg.budget.max_rows:], "peak_waiting": peak, "hint": "cl_waiting > 0 while the database is idle points to the pool, not the database itself then needed check against health_overview.sessions",}

async def host_metrics(cfg: Config, backend: Backend, window: dict[str, str] | None = None) -> dict[str, Any]:
    ref = await backend.reference_time()
    w = parse_window(cfg, ref, window)
    points = await backend.series("host", w.start, w.end, 40)

    if not points:
        return {"error": "нет метрик хоста за окно", "window": w.as_dict()}
    
    series = [{"at": ts.isoformat(), **(payload[0] if payload else {})} for ts, payload in points]

    b = baseline_window(cfg, w) if cfg.ablation.baseline else None
    base_summary = {}

    if b:
        bp = await backend.series("host", b.start, b.end, 20)
        vals = [p[0] for _, p in bp if p]
        for key in ("psi_cpu_avg10", "psi_io_avg10", "cpu_quota_ratio"):
            nums = [v.get(key) for v in vals if v.get(key) is not None]
            if nums:
                base_summary[key] = round(sum(nums) / len(nums), 4)

    return {"window": w.as_dict(), "series": series[-cfg.budget.max_rows:], "baseline_summary": base_summary, "hint": "PSI io avg10 is the cleanest signal of disk saturation; cpu_quota_ratio < 1 means the cgroup is actively throttling",}

async def log_search( cfg: Config, backend: Backend, pattern: str | None = None, window: dict[str, str] | None = None, min_level: str = "LOG", limit: int = 20,) -> dict[str, Any]:
    ref = await backend.reference_time()
    w = parse_window(cfg, ref, window)
    rows = await backend.events("pg_log", w.start, w.end)

    if not rows:
        return {"error": "лог за окно недоступен", "window": w.as_dict()}

    levels = ["DEBUG", "LOG", "INFO", "NOTICE", "WARNING", "ERROR", "FATAL", "PANIC"]
    floor = levels.index(min_level) if min_level in levels else 1

    groups: dict[str, dict[str, Any]] = {}

    for r in rows:
        msg = r.get("message") or ""
        level = (r.get("level") or "LOG").upper()

        if level in levels and levels.index(level) < floor:
            continue
        
        if pattern and pattern.lower() not in msg.lower():
            continue
        
        tpl = log_template(msg)
        g = groups.setdefault(tpl, { "template": tpl, "level": level, "count": 0, "first_at": r.get("ts"), "last_at": r.get("ts"), "example": msg[:400],})
        g["count"] += 1
        g["last_at"] = r.get("ts")

    out = sorted(groups.values(), key=lambda g: -g["count"])

    return envelope(out, budget=cfg.budget, ordered_by="count", window=w, limit=limit, extra={"total_log_lines_in_window": len(rows), "hint": "messages are collapsed into templates; specific numbers are replaced with <n>, and an example of the original line is in the example field"},)