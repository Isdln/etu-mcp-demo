from __future__ import annotations
import argparse
import asyncio
import hashlib
import json
import os
import re
import signal
import csv
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import psycopg
from psycopg.rows import dict_row
from .aliases import SOURCE as ALIAS_SOURCE
from .aliases import next_alias
from .sources import ASH_SQL, LOCK_GRAPH_SQL, SOURCES, SourceSpec

SELF_APP = "pgmon_collector"
_PSI = re.compile(r"avg10=([\d.]+)")

class Collector:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.run_id = args.run_id
        self.aliases: dict[str, str] = {}
        self.alias_rows: list[dict[str, Any]] = []
        self.alias_hash = ""
        self.columns: dict[str, list[str]] = {}
        self.stop = asyncio.Event()

    async def target(self) -> psycopg.AsyncConnection:
        return await psycopg.AsyncConnection.connect(self.args.target_dsn, autocommit=True, application_name=SELF_APP, row_factory=dict_row,)

    async def meta(self) -> psycopg.AsyncConnection:
        return await psycopg.AsyncConnection.connect(self.args.meta_dsn, autocommit=True, application_name=SELF_APP)

    async def resolve_columns(self, conn: psycopg.AsyncConnection) -> None:
        for name, spec in SOURCES.items():
            if spec.sql or not spec.relation:
                continue
            
            async with conn.cursor() as cur:
                await cur.execute("SELECT a.attname FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid WHERE c.relname = %s AND a.attnum > 0 AND NOT a.attisdropped", (spec.relation,),)
                have = {r["attname"] for r in await cur.fetchall()}

            if not have:
                if not spec.optional:
                    print(f"[collector] источник {name} недоступен на этом сервере")

                continue
            
            cols = [c for c in spec.wishlist() if c in have]

            if cols:
                self.columns[name] = cols

    def build_sql(self, spec: SourceSpec) -> str | None:
        if spec.sql:
            return spec.sql
        
        cols = self.columns.get(spec.name)

        if not cols:
            return None

        return f"SELECT {', '.join(cols)} FROM {spec.relation}{f" WHERE {spec.where}" if spec.where else ""}"

    async def write_sample(self, meta: psycopg.AsyncConnection, source: str, taken_at: datetime, payload: list[dict]) -> None:
        async with meta.cursor() as cur:
            await cur.execute("INSERT INTO pgmon.sample (run_id, source, taken_at, payload) VALUES (%s, %s, %s, %s)", (self.run_id, source, taken_at, json.dumps(payload, default=str)),)

    async def write_events(self, meta: psycopg.AsyncConnection, kind: str, rows: list[dict]) -> None:
        if not rows:
            return
        
        async with meta.cursor() as cur:
            await cur.executemany("INSERT INTO pgmon.event (run_id, kind, sampled_at, payload) VALUES (%s, %s, %s, %s)", 
                                  [(self.run_id, kind, r.get("sampled_at") or r.get("ts") or datetime.now(timezone.utc), json.dumps(r, default=str)) for r in rows],)

    async def refresh_aliases(self, target, meta, taken_at: datetime) -> None:
        async with target.cursor() as cur:
            await cur.execute("SELECT queryid, min(left(query, 2000)) AS normalized FROM pg_stat_statements WHERE queryid IS NOT NULL GROUP BY queryid ORDER BY min(queryid)")

            rows = await cur.fetchall()

        changed = False

        for row in rows:
            qid = str(row["queryid"])

            if qid in self.aliases:
                continue
            
            alias = next_alias(len(self.aliases))
            self.aliases[qid] = alias
            self.alias_rows.append({"alias": alias, "queryid": qid, "normalized": row["normalized"], "first_seen": taken_at.isoformat(),})
            changed = True

        digest = hashlib.sha1(json.dumps(sorted(self.aliases.items())).encode()).hexdigest()

        if changed or digest != self.alias_hash:
            self.alias_hash = digest
            await self.write_sample(meta, ALIAS_SOURCE, taken_at, self.alias_rows)

    async def loop_cumulative(self) -> None:
        async with await self.target() as target, await self.meta() as meta:
            await self.resolve_columns(target)
            while not self.stop.is_set():
                now = datetime.now(timezone.utc)
                for name, spec in SOURCES.items():
                    if spec.kind != "cumulative":
                        continue
                    
                    sql = self.build_sql(spec)

                    if not sql:
                        continue
                    
                    try:
                        async with target.cursor() as cur:
                            await cur.execute(sql)
                            payload = await cur.fetchall()

                        await self.write_sample(meta, name, now, payload)

                    except Exception as exc:
                        print(f"[collector] {name}: {exc}")

                try:
                    await self.refresh_aliases(target, meta, now)
                except Exception as exc:
                    print(f"[collector] aliases: {exc}")

                await self._sleep(self.args.snapshot_interval)

    async def loop_instant(self) -> None:
        async with await self.target() as target, await self.meta() as meta:
            while not self.stop.is_set():
                now = datetime.now(timezone.utc)
                for name, spec in SOURCES.items():
                    if spec.kind != "instant":
                        continue
                    
                    sql = self.build_sql(spec)

                    if not sql:
                        continue
                    
                    try:
                        async with target.cursor() as cur:
                            await cur.execute(sql)
                            payload = await cur.fetchall()

                        await self.write_sample(meta, name, now, payload)

                    except Exception as exc:
                        print(f"[collector] {name}: {exc}")

                await self._sleep(self.args.instant_interval)

    async def loop_ash(self) -> None:
        async with await self.target() as target, await self.meta() as meta:
            while not self.stop.is_set():
                try:
                    async with target.cursor() as cur:
                        await cur.execute(ASH_SQL, {"self_app": SELF_APP})
                        ash = await cur.fetchall()
                        await cur.execute(LOCK_GRAPH_SQL, {"self_app": SELF_APP})
                        locks = await cur.fetchall()

                    await self.write_events(meta, "ash", ash)
                    await self.write_events(meta, "locks", locks)

                except Exception as exc:
                    print(f"[collector] ash: {exc}")

                await self._sleep(self.args.ash_interval)

    async def loop_log(self) -> None:
        path = self.args.log_file

        if not path:
            return

        ts_re = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")
        buf = ""
        batch: list[dict[str, Any]] = []

        async with await self.meta() as meta:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                fh.seek(0, os.SEEK_END)
                while not self.stop.is_set():
                    line = fh.readline()
                    if not line:
                        if batch:
                            try:
                                await self.write_events(meta, "pg_log", batch)

                            except Exception as exc:
                                print(f"[collector] pg_log: {exc}")

                            batch = []

                        await self._sleep(1.0)
                        continue

                    buf += line

                    if len(buf) > 65536:
                        buf = ""
                        continue
                    
                    try:
                        parts = next(csv.reader(io.StringIO(buf)))

                    except Exception:
                        continue
                    
                    if len(parts) < 14 or not ts_re.match(parts[0]):
                        if batch and len(buf) < 8192:
                            tail = buf.rstrip("\n")
                            q = tail.rfind('",')

                            if q > 0:
                                tail = tail[:q]

                            batch[-1]["message"] += "\n" + tail
                            buf = ""

                        continue
                    
                    buf = ""
                    batch.append({"ts": parts[0], "sampled_at": parts[0], "user": parts[1], "database": parts[2], "pid": parts[3], "application_name": parts[22] if len(parts) > 22 
                                  else None, "level": parts[11], "message": parts[13], "detail": parts[14] if len(parts) > 14 else None,})

                    if len(batch) >= 50:
                        try:
                            await self.write_events(meta, "pg_log", batch)

                        except Exception as exc:
                            print(f"[collector] pg_log: {exc}")

                        batch = []

    async def loop_pgbouncer(self) -> None:
        if not self.args.pgbouncer_dsn:
            return
        
        async with await self.meta() as meta:
            while not self.stop.is_set():
                try:
                    async with await psycopg.AsyncConnection.connect( self.args.pgbouncer_dsn, autocommit=True, row_factory=dict_row, application_name=SELF_APP,) as conn:

                        async with conn.cursor() as cur:

                            await cur.execute("SHOW POOLS")
                            pools = await cur.fetchall()

                    await self.write_sample(meta, "pgbouncer_pools", datetime.now(timezone.utc), pools)

                except Exception as exc:
                    print(f"[collector] pgbouncer: {exc}")

                await self._sleep(self.args.instant_interval)

    async def loop_host(self) -> None:
        if not self.args.collect_host:
            return
        
        async with await self.meta() as meta:
            while not self.stop.is_set():

                await self.write_sample(meta, "host", datetime.now(timezone.utc), [read_host_metrics()])
                await self._sleep(self.args.instant_interval)

    async def _sleep(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self.stop.wait(), timeout=seconds)

        except asyncio.TimeoutError:
            pass

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.stop.set)

            except NotImplementedError:
                pass
            
        print(f"[collector] run_id={self.run_id} старт")

        await asyncio.gather( self.loop_cumulative(), self.loop_instant(), self.loop_ash(), self.loop_log(), self.loop_pgbouncer(), self.loop_host(),)

        print("[collector] остановлен")

def read_host_metrics() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for resource in ("cpu", "io", "memory"):
        try:
            text = Path(f"/proc/pressure/{resource}").read_text()
            m = _PSI.search(text)

            if m:
                out[f"psi_{resource}_avg10"] = float(m.group(1))

        except OSError:
            pass
        
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()

        if quota != "max":
            out["cpu_quota_ratio"] = round(int(quota) / int(period), 3)

    except (OSError, ValueError):
        pass
    
    try:
        out["loadavg_1m"] = float(Path("/proc/loadavg").read_text().split()[0])

    except (OSError, ValueError):
        pass
    
    return out

def main() -> None:
    p = argparse.ArgumentParser(description="Коллектор телеметрии")
    p.add_argument("--target-dsn", default=os.environ.get("PGMON_TARGET_DSN"), required=not os.environ.get("PGMON_TARGET_DSN"))
    p.add_argument("--meta-dsn", default=os.environ.get("PGMON_META_DSN"), required=not os.environ.get("PGMON_META_DSN"))
    p.add_argument("--run-id", default=os.environ.get("PGMON_RUN_ID", "default"))
    p.add_argument("--snapshot-interval", type=float, default=30.0)
    p.add_argument("--instant-interval", type=float, default=5.0)
    p.add_argument("--ash-interval", type=float, default=1.0)
    p.add_argument("--log-file", default=os.environ.get("PGMON_LOG_FILE"))
    p.add_argument("--pgbouncer-dsn", default=os.environ.get("PGMON_PGBOUNCER_DSN"))
    p.add_argument("--collect-host", action="store_true")

    args = p.parse_args()
    asyncio.run(Collector(args).run())

if __name__ == "__main__":
    main()