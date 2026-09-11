from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

Mode = Literal["live", "replay"]

ALL_GROUPS = ("overview", "queries", "waits", "locks", "objects", "maintenance", "pool", "host", "logs", "answer",)

BUILTIN_ABLATIONS: dict[str, dict[str, Any]] = {
    "full": {"groups": list(ALL_GROUPS), "baseline": True,},
    "no_ash": {"groups": [g for g in ALL_GROUPS if g != "waits"], "baseline": True,},
    "no_logs": {"groups": [g for g in ALL_GROUPS if g != "logs"], "baseline": True,},
    "no_baseline": {"groups": list(ALL_GROUPS), "baseline": False,},
    "no_xmin_helper": {"groups": list(ALL_GROUPS), "baseline": True, "disabled_tools": ["xmin_horizon"],},
    "minimal": {"groups": ["overview", "queries", "answer"], "baseline": True,},
}

@dataclass(frozen=True)
class Ablation:
    name: str = "full"
    groups: tuple[str, ...] = ()
    disabled_tools: tuple[str, ...] = ()
    baseline: bool = True

    @classmethod
    def load(cls) -> "Ablation":
        name = os.environ.get("PGMON_ABLATION", "full")
        path = os.environ.get("PGMON_ABLATION_FILE")

        if path:
            spec = json.loads(Path(path).read_text(encoding="utf-8"))[name]

        else:

            if name not in BUILTIN_ABLATIONS:
                raise SystemExit(f"неизвестный профиль аблации {name!r}; доступны: {', '.join(sorted(BUILTIN_ABLATIONS))}")
            
            spec = BUILTIN_ABLATIONS[name]

        return cls(name=name, groups=tuple(spec.get("groups", ALL_GROUPS)), disabled_tools=tuple(spec.get("disabled_tools", ())), baseline=bool(spec.get("baseline", True)),)

    def allows(self, group: str, tool: str) -> bool:
        return group in self.groups and tool not in self.disabled_tools

@dataclass(frozen=True)
class Budget:
    max_rows: int = 25
    max_text_chars: int = 320
    max_response_chars: int = 14000

    @classmethod
    def load(cls) -> "Budget":
        return cls(max_rows=int(os.environ.get("PGMON_MAX_ROWS", 25)), max_text_chars=int(os.environ.get("PGMON_MAX_TEXT_CHARS", 320)), 
                   max_response_chars=int(os.environ.get("PGMON_MAX_RESPONSE_CHARS", 14000)),)

def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    
    dt = datetime.fromisoformat(value)

    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@dataclass
class Config:
    mode: Mode = "live"
    run_id: str = "default"
    scenario_id: str | None = None
    meta_dsn: str | None = None
    bundle_path: Path | None = None
    clone_dsn: str | None = None
    target_dsn: str | None = None
    incident_from: datetime | None = None
    incident_to: datetime | None = None
    default_window_seconds: int = 900
    baseline_offset_seconds: int = 1800

    audit_path: Path = field(default_factory=lambda: Path("./audit"))
    ablation: Ablation = field(default_factory=Ablation)
    budget: Budget = field(default_factory=Budget)

    @classmethod
    def from_env(cls) -> "Config":
        mode: Mode = os.environ.get("PGMON_MODE", "live")  # type: ignore[assignment]
        bundle = os.environ.get("PGMON_BUNDLE")

        cfg = cls(
            mode=mode,
            run_id=os.environ.get("PGMON_RUN_ID", "default"),
            scenario_id=os.environ.get("PGMON_SCENARIO_ID"),
            meta_dsn=os.environ.get("PGMON_META_DSN"),
            bundle_path=Path(bundle) if bundle else None,
            clone_dsn=os.environ.get("PGMON_CLONE_DSN"),
            target_dsn=os.environ.get("PGMON_TARGET_DSN"),
            incident_from=_dt(os.environ.get("PGMON_WINDOW_FROM")),
            incident_to=_dt(os.environ.get("PGMON_WINDOW_TO")),
            default_window_seconds=int(os.environ.get("PGMON_WINDOW_SECONDS", 900)),
            baseline_offset_seconds=int(os.environ.get("PGMON_BASELINE_OFFSET", 1800)),
            audit_path=Path(os.environ.get("PGMON_AUDIT_DIR", "./audit")),
            ablation=Ablation.load(),
            budget=Budget.load(),
        )

        if cfg.mode == "live" and not cfg.meta_dsn:
            raise SystemExit("в режиме live требуется PGMON_META_DSN")
        
        if cfg.mode == "replay" and not cfg.bundle_path:
            raise SystemExit("в режиме replay требуется PGMON_BUNDLE")
        
        return cfg

    def baseline_for(self, start: datetime, end: datetime) -> tuple[datetime, datetime]:
        duration = end - start
        b_end = start - timedelta(seconds=self.baseline_offset_seconds)
        return b_end - duration, b_end