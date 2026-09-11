from __future__ import annotations
from typing import Any
from .aliases import load_aliases
from .backends import Backend
from .config import Config
from .sources import as_rate, num, SOURCES, compute_delta
from .util import Window, baseline_window, clamp, envelope, parse_window, ratio

ORDERINGS = {"total_time": "d_total_exec_time", "calls": "d_calls", "mean_time": "mean_exec_time", "reads": "d_shared_blks_read", "temp": "d_temp_blks_written", "wal": "d_wal_bytes", "rows": "d_rows",}

def _sum(rows: list[dict[str, Any]], col: str) -> float:
    return sum(num(r.get(col)) for r in rows)

async def health_overview(cfg: Config, backend: Backend, window: dict[str, str] | None = None) -> dict[str, Any]:
    ref = await backend.reference_time()
    w = parse_window(cfg, ref, window)
    b = baseline_window(cfg, w) if cfg.ablation.baseline else None

    db_rows, meta = await backend.delta("pg_stat_database", w.start, w.end)
    db_base: list[dict[str, Any]] = []

    if b:
        db_base, _ = await backend.delta("pg_stat_database", b.start, b.end)

    def agg(rows: list[dict[str, Any]], seconds: float) -> dict[str, Any]:
        commits = _sum(rows, "d_xact_commit")
        rollbacks = _sum(rows, "d_xact_rollback")
        hit = _sum(rows, "d_blks_hit")
        read = _sum(rows, "d_blks_read")

        return {"tps": as_rate(commits + rollbacks, seconds), "rollback_share": round(rollbacks / (commits + rollbacks), 4) if (commits + rollbacks) else None, 
                "cache_hit_ratio": round(hit / (hit + read), 4) if (hit + read) else None, "blks_read_per_s": as_rate(read, seconds), "temp_bytes_per_s": as_rate(_sum(rows, "d_temp_bytes"), seconds),
                "deadlocks": _sum(rows, "d_deadlocks"), "tup_returned_per_s": as_rate(_sum(rows, "d_tup_returned"), seconds),}

    current = agg(db_rows, w.seconds)
    baseline_vals = agg(db_base, b.seconds) if b else {}

    comparison = {k: {"window": current.get(k), "baseline": baseline_vals.get(k), "ratio": ratio(current.get(k), baseline_vals.get(k))} for k in current} if b else {k: {"window": v} for k, v in current.items()}

    st_rows, st_meta = await backend.delta("pg_stat_statements", w.start, w.end)
    calls = _sum(st_rows, "d_calls")
    total_ms = _sum(st_rows, "d_total_exec_time")

    latency = {"weighted_mean_exec_ms": round(total_ms / calls, 3) if calls else None, "calls": calls, "distinct_statements": len(st_rows),
               "note": "перцентилей в pg_stat_statements нет; форму распределения смотрите в wait_profile и log_search",}

    ash = await backend.events("ash", w.start, w.end)
    sessions: dict[str, Any] = {}

    if ash:
        samples = len({r["sampled_at"] for r in ash})
        by_state: dict[str, int] = {}
        by_wait: dict[str, int] = {}
        for row in ash:
            by_state[row.get("state") or "?"] = by_state.get(row.get("state") or "?", 0) + 1
            key = row.get("wait_event_type") or "CPU"
            by_wait[key] = by_wait.get(key, 0) + 1

        sessions = {"avg_active_sessions": round(sum(v for k, v in by_state.items() if k == "active") / samples, 2) if samples else None, "state_share": _share(by_state), "wait_type_share": _share(by_wait),}

    notes = []
    if meta.get("stats_reset_detected") or st_meta.get("stats_reset_detected"):
        notes.append("Внимание: внутри окна обнаружен сброс статистики, дельты занижены")

    if not cfg.ablation.baseline:
        notes.append("сравнение с эталонным окном отключено профилем аблации")

    return envelope([], budget=cfg.budget, ordered_by="-", window=w, baseline=b, notes=notes, extra={"throughput": comparison, "latency": latency, "sessions": sessions, "delta_meta": meta,},)

def _share(counts: dict[str, int]) -> dict[str, float]:
    total = sum(counts.values()) or 1
    return {k: round(v / total, 3) for k, v in sorted(counts.items(), key=lambda kv: -kv[1])[:8]}

async def top_queries(cfg: Config, backend: Backend, window: dict[str, str] | None = None, order_by: str = "total_time", limit: int = 15,) -> dict[str, Any]:
    if order_by not in ORDERINGS:
        return {"error": f"order_by должен быть одним из {sorted(ORDERINGS)}"}

    ref = await backend.reference_time()
    w = parse_window(cfg, ref, window)
    rows, meta = await backend.delta("pg_stat_statements", w.start, w.end)
    aliases = await load_aliases(backend, w.end)

    base_by_qid: dict[str, dict[str, Any]] = {}
    b: Window | None = None
    if cfg.ablation.baseline:
        b = baseline_window(cfg, w)
        base_rows, _ = await backend.delta("pg_stat_statements", b.start, b.end)
        base_by_qid = {str(r.get("queryid")): r for r in base_rows}

    out: list[dict[str, Any]] = []
    seconds = meta.get("effective_seconds") or w.seconds
    for r in rows:
        d_calls = num(r.get("d_calls"))
        d_total = num(r.get("d_total_exec_time"))

        if d_calls <= 0:
            continue
        
        qid = str(r.get("queryid"))

        item = {"alias": aliases.alias(qid), "calls": d_calls, "calls_per_s": as_rate(d_calls, seconds), "total_exec_ms": round(d_total, 1), "mean_exec_ms": round(d_total / d_calls, 3), 
                "rows_per_call": round(num(r.get("d_rows")) / d_calls, 2), "shared_read": r.get("d_shared_blks_read"), "shared_hit": r.get("d_shared_blks_hit"), "temp_written": r.get("d_temp_blks_written"), 
                "wal_bytes": r.get("d_wal_bytes"), "first_seen_in_window": r.get("_first_seen_in_window"),}

        if base_by_qid:
            prev = base_by_qid.get(qid)
            prev_calls = num((prev or {}).get("d_calls"))
            prev_mean = (num((prev or {}).get("d_total_exec_time")) / prev_calls if prev_calls else None)

            item["baseline"] = {"mean_exec_ms": round(prev_mean, 3) if prev_mean else None, "mean_ratio": ratio(item["mean_exec_ms"], prev_mean),
                                "calls_ratio": ratio(d_calls, prev_calls or None), "present_in_baseline": prev is not None,}
        out.append(item)

    key = ORDERINGS[order_by]

    sort_field = {"d_total_exec_time": "total_exec_ms", "d_calls": "calls", "mean_exec_time": "mean_exec_ms", "d_shared_blks_read": "shared_read", "d_temp_blks_written": "temp_written",
                  "d_wal_bytes": "wal_bytes", "d_rows": "rows_per_call",}[key]
    out.sort(key=lambda x: num(x.get(sort_field)), reverse=True)

    notes = ["метрики дельты за окно, не кумулятивные значения"]

    if meta.get("stats_reset_detected"):
        notes.append("Внимание: сброс pg_stat_statements внутри окна")

    return envelope(out, budget=cfg.budget, ordered_by=order_by, window=w, baseline=b,limit=limit, notes=notes, extra={"delta_meta": meta},)


async def query_detail(cfg: Config, backend: Backend, alias: str, window: dict[str, str] | None = None) -> dict[str, Any]:
    ref = await backend.reference_time()
    w = parse_window(cfg, ref, window)
    aliases = await load_aliases(backend, w.end)
    entry = aliases.entry(alias)

    if not entry:
        return {"error": f"псевдоним {alias!r} не найден", "hint": "get the current aliases via top_queries"}

    qid = str(entry["queryid"])
    rows, meta = await backend.delta("pg_stat_statements", w.start, w.end)
    row = next((r for r in rows if str(r.get("queryid")) == qid), None)

    if row is None:
        return {"error": f"{alias} не выполнялся в окне", "window": w.as_dict()}

    spec = SOURCES["pg_stat_statements"]
    points = await backend.series("pg_stat_statements", w.start, w.end, max_points=min(cfg.budget.max_rows + 1, 40),)
    trend: list[dict[str, Any]] = []

    for (t0, p0), (t1, p1) in zip(points, points[1:]):
        d, _ = compute_delta(spec, p0, p1)
        cur = next((x for x in d if str(x.get("queryid")) == qid), None)

        if not cur:
            continue
        
        calls = num(cur.get("d_calls"))
        interval = (t1 - t0).total_seconds() or 1.0
        trend.append({"at": t1.isoformat(), "interval_s": round(interval, 1), "calls_per_s": as_rate(calls, interval), "mean_exec_ms": round(num(cur.get("d_total_exec_time")) / calls, 3)
                      if calls else None, "shared_read_per_s": as_rate(cur.get("d_shared_blks_read"), interval), "temp_written_per_s": as_rate(cur.get("d_temp_blks_written"), interval),})

    trend_truncated = len(trend) > cfg.budget.max_rows
    trend = trend[: cfg.budget.max_rows]

    calls = num(row.get("d_calls"))
    return {"alias": alias, "normalized_sql": clamp(entry.get("normalized"), 2000), "window": w.as_dict(),
            "totals": {"calls": calls, "total_exec_ms": round(num(row.get("d_total_exec_time")), 1), "mean_exec_ms": round(num(row.get("d_total_exec_time")) / calls, 3) if calls else None,
                       "min_exec_ms": row.get("min_exec_time"), "max_exec_ms": row.get("max_exec_time"), "stddev_exec_ms": row.get("stddev_exec_time"), "rows": row.get("d_rows"), 
                       "shared_hit": row.get("d_shared_blks_hit"), "shared_read": row.get("d_shared_blks_read"), "shared_dirtied": row.get("d_shared_blks_dirtied"),
                       "temp_read": row.get("d_temp_blks_read"), "temp_written": row.get("d_temp_blks_written"), "wal_bytes": row.get("d_wal_bytes"),},
            "trend": trend, "trend_truncated": trend_truncated, "delta_meta": meta, "hint": "step-wise increase in mean_exec_ms with unchanged calls_per_s usually indicates a plan change, whereas a gradual increase suggests growing data volume or contention",}