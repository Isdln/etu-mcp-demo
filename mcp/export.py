from __future__ import annotations
import argparse
import gzip
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import psycopg
from psycopg.rows import dict_row

def _dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))

    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

def main() -> None:
    p = argparse.ArgumentParser(description="Экспорт снапшота")
    p.add_argument("--meta-dsn", default=os.environ.get("PGMON_META_DSN"), required=False)
    p.add_argument("--run-id", required=True)
    p.add_argument("--scenario-id", default=None)
    p.add_argument("--from", dest="start", required=True, help="ISO-8601")
    p.add_argument("--to", dest="end", required=True, help="ISO-8601")
    p.add_argument("--pad-before", type=float, default=3600.0, help="секунд до окна")
    p.add_argument("--pad-after", type=float, default=600.0)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    start = _dt(args.start) - timedelta(seconds=args.pad_before)
    end = _dt(args.end) + timedelta(seconds=args.pad_after)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    with psycopg.connect(args.meta_dsn, row_factory=dict_row) as conn:
        with gzip.open(out / "samples.jsonl.gz", "wt", encoding="utf-8") as fh:
            with conn.cursor(name="samples") as cur:
                cur.execute("SELECT source, taken_at, payload FROM pgmon.sample WHERE run_id = %s AND taken_at BETWEEN %s AND %s ORDER BY taken_at", (args.run_id, start, end),)
                n_samples = 0

                for row in cur:
                    fh.write(json.dumps({"source": row["source"], "taken_at": row["taken_at"].isoformat(), "payload": row["payload"],}, ensure_ascii=False, default=str) + "\n")
                    n_samples += 1

        with gzip.open(out / "events.jsonl.gz", "wt", encoding="utf-8") as fh:
            with conn.cursor(name="events") as cur:
                cur.execute("SELECT kind, sampled_at, payload FROM pgmon.event WHERE run_id = %s AND sampled_at BETWEEN %s AND %s ORDER BY sampled_at", (args.run_id, start, end),)
                n_events = 0

                for row in cur:
                    fh.write(json.dumps({"kind": row["kind"], "sampled_at": row["sampled_at"].isoformat(), "payload": row["payload"],}, ensure_ascii=False, default=str) + "\n")
                    n_events += 1

    manifest = {
        "run_id": args.run_id, "scenario_id": args.scenario_id, "window_from": _dt(args.start).isoformat(), "window_to": _dt(args.end).isoformat(), "bundle_from": start.isoformat(),
        "bundle_to": end.isoformat(), "samples": n_samples, "events": n_events, "exported_at": datetime.now(timezone.utc).isoformat(),
    }

    (out / "manifest.json").write_text( json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"\nбандл готов: {out}\nзапуск реплея: PGMON_MODE=replay PGMON_BUNDLE={out} pgmon-mcp")

if __name__ == "__main__":
    main()