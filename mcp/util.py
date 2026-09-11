from __future__ import annotations
import functools
import json
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable
from .config import Budget, Config

@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime
    label: str = "window"

    @property
    def seconds(self) -> float:
        return (self.end - self.start).total_seconds()

    def as_dict(self) -> dict[str, Any]:
        return {"from": self.start.isoformat(), "to": self.end.isoformat(), "duration_s": round(self.seconds, 1),}

def parse_window(cfg: Config, reference: datetime, window: dict[str, str] | None,) -> Window:

    if window:
        start = _iso(window.get("from"))
        end = _iso(window.get("to"))

        if start and end:
            return Window(start, end, "explicit")
        
        if end and not start:
            return Window(end - timedelta(seconds=cfg.default_window_seconds), end, "explicit")
        
        if start and not end:
            return Window(start, min(reference, start + timedelta(seconds=cfg.default_window_seconds)), "explicit")

    if cfg.incident_from and cfg.incident_to:
        return Window(cfg.incident_from, cfg.incident_to, "incident")

    return Window(reference - timedelta(seconds=cfg.default_window_seconds), reference, "default",)

def _iso(value: str | None) -> datetime | None:
    if not value:
        return None
    
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))

    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

def baseline_window(cfg: Config, w: Window) -> Window:
    start, end = cfg.baseline_for(w.start, w.end)

    return Window(start, end, "baseline")

def ratio(current: float | None, base: float | None) -> float | None:
    if current is None or base is None:
        return None
    
    if base == 0:
        return None if current == 0 else float("inf")
    
    return round(current / base, 3)

def clamp(text: Any, limit: int) -> Any:
    if not isinstance(text, str) or len(text) <= limit:
        return text
    
    return text[:limit] + f"… [+{len(text) - limit} симв.]"

def envelope(rows: list[dict[str, Any]], *, budget: Budget, ordered_by: str, window: Window | None = None, baseline: Window | None = None, limit: int | None = None, 
             notes: list[str] | None = None, extra: dict[str, Any] | None = None,) -> dict[str, Any]:
    total = len(rows)
    cap = min(limit or budget.max_rows, budget.max_rows)
    shown = rows[:cap]
    shown = [{k: clamp(v, budget.max_text_chars) for k, v in row.items()} for row in shown]

    payload: dict[str, Any] = {
        "rows": shown,
        "shown": len(shown),
        "total_rows": total,
        "truncated": total > len(shown),
        "ordered_by": ordered_by,
    }

    if window:
        payload["window"] = window.as_dict()

    if baseline:
        payload["baseline_window"] = baseline.as_dict()

    if notes:
        payload["notes"] = notes

    if extra:
        payload.update(extra)

    while len(json.dumps(payload, default=str)) > budget.max_response_chars and payload["rows"]:
        payload["rows"].pop()
        payload["shown"] = len(payload["rows"])
        payload["truncated"] = True
        payload["size_capped"] = True

    return payload

class Audit:
    def __init__(self, cfg: Config) -> None:
        cfg.audit_path.mkdir(parents=True, exist_ok=True)
        self.path = cfg.audit_path / f"{cfg.run_id}.jsonl"
        self.cfg = cfg
        self.session_id = uuid.uuid4().hex[:12]
        self.seq = 0

    def record(self, **fields: Any) -> None:
        self.seq += 1
        entry = {"ts": datetime.now(timezone.utc).isoformat(), "session_id": self.session_id, "seq": self.seq, "run_id": self.cfg.run_id, "scenario_id": self.cfg.scenario_id, 
                 "ablation": self.cfg.ablation.name, "mode": self.cfg.mode, **fields,}

        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

def audited(audit: Audit, name: str, group: str) -> Callable:
    def decorator(fn: Callable[..., Awaitable[dict]]) -> Callable[..., Awaitable[dict]]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> dict:
            started = time.perf_counter()
            error = None
            result: dict[str, Any] = {}

            try:
                result = await fn(*args, **kwargs)

                return result
            
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                result = {"error": error}

                return result
            
            finally:
                body = json.dumps(result, default=str, ensure_ascii=False)
                audit.record(tool=name, group=group,  args={k: v for k, v in kwargs.items() if k != "ctx"}, latency_ms=round((time.perf_counter() - started) * 1000, 1), response_chars=len(body),
                             rows_returned=result.get("shown"), total_rows=result.get("total_rows"), truncated=result.get("truncated"), error=error,)

        return wrapper

    return decorator

_NUM = re.compile(r"\b\d+(\.\d+)?\b")
_QUOTED = re.compile(r"'[^']*'")
_DQUOTED = re.compile(r'"[^"]*"')
_HEX = re.compile(r"\b[0-9A-F]{2,}/[0-9A-F]+\b")

def log_template(message: str) -> str:
    t = _QUOTED.sub("'?'", message)
    t = _DQUOTED.sub('"?"', t)
    t = _HEX.sub("<lsn>", t)
    t = _NUM.sub("<n>", t)
    
    return re.sub(r"\s+", " ", t).strip()[:220]