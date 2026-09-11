from __future__ import annotations
import gzip
import json
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from psycopg_pool import AsyncConnectionPool
from psycopg.rows import tuple_row
from typing import Any, Iterable
from .config import Config
from .sources import SOURCES, SourceSpec, compute_delta


class Backend(ABC):

    @abstractmethod
    async def reference_time(self) -> datetime: pass

    @abstractmethod
    async def snapshot_at(self, source: str, at: datetime) -> list[dict[str, Any]]: pass

    @abstractmethod
    async def bounds(self, source: str, start: datetime, end: datetime) -> tuple[list[dict[str, Any]], list[dict[str, Any]], datetime | None, datetime | None]: pass

    @abstractmethod
    async def series(self, source: str, start: datetime, end: datetime, max_points: int = 60) -> list[tuple[datetime, list[dict[str, Any]]]]: pass

    @abstractmethod
    async def events(self, kind: str, start: datetime, end: datetime, limit: int = 20000) -> list[dict[str, Any]]: pass

    async def close(self) -> None:
        return None

    async def delta(self, source: str, start: datetime, end: datetime) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        spec = SOURCES[source]
        first, last, t0, t1 = await self.bounds(source, start, end)
        rows, reset = compute_delta(spec, first, last)
        meta = {"delta_between": [t0.isoformat() if t0 else None, t1.isoformat() if t1 else None], "effective_seconds": (t1 - t0).total_seconds() if t0 and t1 else None,
                "stats_reset_detected": reset, "cumulative_source": True,}

        return rows, meta

class MetaStoreBackend(Backend):
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._pool = None

    async def _p(self):
        if self._pool is None:
            self._pool = AsyncConnectionPool( self.cfg.meta_dsn, min_size=1, max_size=4, kwargs={"application_name": "pgmon_mcp_reader"}, open=False,)
            await self._pool.open(wait=True)

        return self._pool

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()

    async def _fetch(self, sql: str, params: dict[str, Any]) -> list[tuple]:
        pool = await self._p()
        async with pool.connection() as conn:
            conn.row_factory = tuple_row

            async with conn.cursor() as cur:
                await cur.execute(sql, params)
            
                return await cur.fetchall()

    async def reference_time(self) -> datetime:
        rows = await self._fetch("SELECT max(taken_at) FROM pgmon.sample WHERE run_id = %(run)s", {"run": self.cfg.run_id},)

        return rows[0][0] or datetime.now(timezone.utc)

    async def snapshot_at(self, source: str, at: datetime) -> list[dict[str, Any]]:
        rows = await self._fetch("SELECT payload FROM pgmon.sample WHERE run_id = %(run)s AND source = %(src)s AND taken_at <= %(at)s ORDER BY taken_at DESC LIMIT 1", {"run": self.cfg.run_id, "src": source, "at": at},)

        return list(rows[0][0]) if rows else []

    async def bounds(self, source, start, end):
        rows = await self._fetch(""" (SELECT taken_at, payload FROM pgmon.sample WHERE run_id = %(run)s AND source = %(src)s AND taken_at BETWEEN %(a)s AND %(b)s ORDER BY taken_at ASC LIMIT 1)
            UNION ALL (SELECT taken_at, payload FROM pgmon.sample WHERE run_id = %(run)s AND source = %(src)s AND taken_at BETWEEN %(a)s AND %(b)s ORDER BY taken_at DESC LIMIT 1)""",
            {"run": self.cfg.run_id, "src": source, "a": start, "b": end},)
        
        if not rows:
            return [], [], None, None
        
        (t0, p0), (t1, p1) = rows[0], rows[-1]

        return list(p0), list(p1), t0, t1

    async def series(self, source, start, end, max_points=60):
        rows = await self._fetch("SELECT taken_at, payload FROM pgmon.sample WHERE run_id = %(run)s AND source = %(src)s AND taken_at BETWEEN %(a)s AND %(b)s ORDER BY taken_at", 
                                 {"run": self.cfg.run_id, "src": source, "a": start, "b": end},)
        
        return _thin([(t, list(p)) for t, p in rows], max_points)

    async def events(self, kind, start, end, limit=20000):
        rows = await self._fetch("SELECT payload FROM pgmon.event WHERE run_id = %(run)s AND kind = %(kind)s AND sampled_at BETWEEN %(a)s AND %(b)s ORDER BY sampled_at LIMIT %(lim)s",
                                 {"run": self.cfg.run_id, "kind": kind, "a": start, "b": end, "lim": limit},)

        return [r[0] for r in rows]

class ReplayBackend(Backend):
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.samples: dict[str, list[tuple[datetime, list[dict]]]] = {}
        self.event_log: dict[str, list[tuple[datetime, dict]]] = {}
        self.manifest: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        base = self.cfg.bundle_path
        assert base is not None
        manifest = base / "manifest.json"
        if manifest.exists():
            self.manifest = json.loads(manifest.read_text(encoding="utf-8"))

        for line in _read_jsonl(base / "samples.jsonl.gz"):
            ts = datetime.fromisoformat(line["taken_at"])
            self.samples.setdefault(line["source"], []).append((ts, line["payload"]))

        for arr in self.samples.values():
            arr.sort(key=lambda x: x[0])

        for line in _read_jsonl(base / "events.jsonl.gz"):
            ts = datetime.fromisoformat(line["sampled_at"])
            self.event_log.setdefault(line["kind"], []).append((ts, line["payload"]))

        for arr in self.event_log.values():
            arr.sort(key=lambda x: x[0])

    async def reference_time(self) -> datetime:
        if self.manifest.get("window_to"):
            return datetime.fromisoformat(self.manifest["window_to"])
        
        latest = [arr[-1][0] for arr in self.samples.values() if arr]

        return max(latest) if latest else datetime.now(timezone.utc)

    async def snapshot_at(self, source, at):
        arr = self.samples.get(source, [])
        chosen: list[dict] = []
        for ts, payload in arr:

            if ts <= at:
                chosen = payload

            else:
                break
            
        return chosen

    async def bounds(self, source, start, end):
        arr = [(t, p) for t, p in self.samples.get(source, []) if start <= t <= end]

        if not arr:
            return [], [], None, None
        
        return arr[0][1], arr[-1][1], arr[0][0], arr[-1][0]

    async def series(self, source, start, end, max_points=60):
        arr = [(t, p) for t, p in self.samples.get(source, []) if start <= t <= end]

        return _thin(arr, max_points)

    async def events(self, kind, start, end, limit=20000):
        return [p for t, p in self.event_log.get(kind, []) if start <= t <= end][:limit]

def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return []
    
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()

            if line:
                yield json.loads(line)

def _thin(arr: list, max_points: int) -> list:
    if len(arr) <= max_points:
        return arr
    
    step = len(arr) / max_points
    
    return [arr[int(i * step)] for i in range(max_points)]

def build_backend(cfg: Config) -> Backend:
    return MetaStoreBackend(cfg) if cfg.mode == "live" else ReplayBackend(cfg)