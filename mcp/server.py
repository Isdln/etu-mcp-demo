from __future__ import annotations
import asyncio
from typing import Any

try:
    from mcp.server.mcpserver import MCPServer as _Server

except ModuleNotFoundError:
    from mcp.server.fastmcp import FastMCP as _Server

try:
    from mcp.types import ToolAnnotations

except ImportError:
    ToolAnnotations = None

from . import tools_answer as ta
from . import tools_core as tc
from . import tools_diag as td
from .backends import Backend, build_backend
from .config import Config
from .util import Audit, audited

INSTRUCTIONS = """Tools for observing a PostgreSQL instance under load.
What's important to know about the data you receive:
All metrics from pg_stat_* are returned as DELTAS over the window, not as cumulative values since startup. The delta_meta field shows between which moments the delta was actually calculated.
If a warning about a statistics reset appears in the notes field, the values are understated and cannot be relied upon quantitatively.
Queries are labeled with stable aliases Q01, Q02, and so on. Obtain them via top_queries and afterward refer only to the alias.
Every list-type response is limited in the number of rows. The truncated and total_rows fields tell you whether you are seeing the full list. 
Do not conclude "there are no more of these" if truncated=true.
Execution plans are captured from a CLONE of the database, not from the production instance.
The default for all windows is the incident window of the current scenario.
A workflow that is usually shorter than others: 
health_overview -> wait_profile (to determine the problem class by wait type) -> then proceed down the branch: Lock -> lock_graph and sessions; IO -> host_metrics and table_health; 
CPU or rising query cost -> top_queries and query_detail; suspicion of MVCC issues -> xmin_horizon and table_health.
Once you've finished the investigation, call submit_diagnosis exactly once. In root_causes, list only root causes; 
list observed consequences separately in affected_entities -> they are not penalized.
"""

def build_server() -> tuple[Any, Config, Backend, Audit]:
    cfg = Config.from_env()
    backend = build_backend(cfg)
    audit = Audit(cfg)
    mcp = _Server("pgmon", instructions=INSTRUCTIONS)

    ab = cfg.ablation
    reg: list[str] = []
    registered: list[str] = []

    def expose(group: str, name: str, fn) -> None:
        if not ab.allows(group, name):
            return
        
        registered.append(name)
        wrapped = audited(audit, name, group)(fn)
        wrapped.__name__ = name
        kwargs: dict[str, Any] = {"name": name}

        if ToolAnnotations is not None:
            kwargs["annotations"] = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True,)

        try:
            mcp.tool(**kwargs)(wrapped)

        except TypeError:
            mcp.tool(name=name)(wrapped)

        reg.append(name)

    async def health_overview(window: dict[str, str] | None = None) -> dict[str, Any]:
        "Database health summary for the window: throughput, latency, cache hit ratio, session composition relative to the baseline window."
        return await tc.health_overview(cfg, backend, window)
    
    expose("overview", "health_overview", health_overview)

    async def top_queries(window: dict[str, str] | None = None, order_by: str = "total_time", limit: int = 15, ) -> dict[str, Any]:
        "The heaviest queries in the window by pg_stat_statements deltas. Order_by: total_time | calls | mean_time | reads | temp | wal | rows."
        return await tc.top_queries(cfg, backend, window, order_by, limit)

    async def query_detail( alias: str, window: dict[str, str] | None = None) -> dict[str, Any]:
        "Details for a single query (alias Q01, Q02, so on), including point-by-point dynamics: a step change indicates a plan switch.."
        return await tc.query_detail(cfg, backend, alias, window)

    expose("queries", "top_queries", top_queries)
    expose("queries", "query_detail", query_detail)

    async def wait_profile(window: dict[str, str] | None = None, group_by: str = "wait_event", limit: int = 20,) -> dict[str, Any]:
        "Wait-event profile from samples of active sessions. group_by: wait_event | wait_event_type | query | backend_type | state | time."
        return await td.wait_profile(cfg, backend, window, group_by, limit)

    async def sessions(at: str | None = None, state: str | None = None, min_age_s: float = 0.0, limit: int = 20,) -> dict[str, Any]:
        "Snapshot of sessions at a point in time: state, wait event, transaction age, backend_xmin."
        return await td.sessions(cfg, backend, at, state, min_age_s, limit)

    expose("waits", "wait_profile", wait_profile)
    expose("waits", "sessions", sessions)

    async def lock_graph(
        window: dict[str, str] | None = None, limit: int = 20) -> dict[str, Any]:
        "Lock tree for the window: who is waiting on whom, chain depth, and root blockers."
        return await td.lock_graph(cfg, backend, window, limit)

    expose("locks", "lock_graph", lock_graph)

    async def table_health(relation: str | None = None, window: dict[str, str] | None = None, order_by: str = "dead_ratio", limit: int = 15,) -> dict[str, Any]:
        "Table health: dead tuples, sizes, frozenxid age, time of last vacuum and analyze, scan activity trends."
        return await td.table_health(cfg, backend, relation, window, order_by, limit)

    async def index_health(relation: str | None = None, window: dict[str, str] | None = None,  limit: int = 20,) -> dict[str, Any]:
        "Index status: usage compared to the baseline window, size, validity."
        return await td.index_health(cfg, backend, relation, window, limit)

    async def schema_object(relation: str) -> dict[str, Any]:
        "Object definition: kind, sizes, reloptions, list of indexes."
        return await td.schema_object(cfg, backend, relation)

    expose("objects", "table_health", table_health)
    expose("objects", "index_health", index_health)
    expose("objects", "schema_object", schema_object)

    async def xmin_horizon(at: str | None = None) -> dict[str, Any]:
        "Who is holding back the vacuum horizon: replication slots, long-running transactions, prepared 2PC transactions."
        return await td.xmin_horizon(cfg, backend, at)

    async def maintenance_status(window: dict[str, str] | None = None, limit: int = 20) -> dict[str, Any]:
        "Currently running vacuum operations and autovacuum log entries."
        return await td.maintenance_status(cfg, backend, window, limit)

    expose("maintenance", "xmin_horizon", xmin_horizon)
    expose("maintenance", "maintenance_status", maintenance_status)

    async def pool_status(window: dict[str, str] | None = None) -> dict[str, Any]:
        "PgBouncer pool status: waiting clients and maximum wait time."
        return await td.pool_status(cfg, backend, window)

    async def host_metrics(window: dict[str, str] | None = None) -> dict[str, Any]:
        "Host metrics: CPU, I/O, memory, PSI, cgroup limits."
        return await td.host_metrics(cfg, backend, window)

    expose("pool", "pool_status", pool_status)
    expose("host", "host_metrics", host_metrics)

    async def log_search(pattern: str | None = None, window: dict[str, str] | None = None, min_level: str = "LOG", limit: int = 20,) -> dict[str, Any]:
        "Server log, collapsed into message templates with counts."
        return await td.log_search(cfg, backend, pattern, window, min_level, limit)

    expose("logs", "log_search", log_search)

    async def submit_diagnosis(incident_detected: bool, root_causes: list[dict[str, str]] | None = None, affected_entities: list[dict[str, str]] | None = None, confidence: float | None = None, 
                               symptom_onset: str | None = None, evidence: list[dict[str, str]] | None = None, recommended_actions: list[dict[str, str]] | None = None, ) -> dict[str, Any]:
        "Submit the final diagnosis. root_causes — only root causes; list consequences in affected_entities."
        return await ta.submit_diagnosis(cfg, audit, incident_detected, root_causes, affected_entities, confidence, symptom_onset, evidence, recommended_actions,)

    expose("answer", "submit_diagnosis", submit_diagnosis)

    audit.record(tool="__startup__", group="-", tools=list(registered), groups=list(cfg.ablation.groups), baseline=cfg.ablation.baseline,)

    return mcp, cfg, backend, audit

def main() -> None:
    server = build_server()

    if isinstance(server, tuple):
        server = server[0]

    server.run()

if __name__ == "__main__":
    main()