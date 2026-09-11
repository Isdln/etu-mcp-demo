from __future__ import annotations
import json
import re
from datetime import datetime, timezone
from typing import Any
from .backends import Backend
from .config import Config
from .util import Audit

ENTITY_TYPES = {"session", "index", "relation", "query_fingerprint", "connection_pool", "host_resource",}

CAUSE_CLASSES = {"xmin_horizon_block", "lock_contention", "missing_index", "resource_throttle", "pool_exhaustion", "benign_workload_change",}

async def submit_diagnosis(cfg: Config, audit: Audit, incident_detected: bool, root_causes: list[dict[str, str]] | None = None, affected_entities: list[dict[str, str]] | None = None, 
                           confidence: float | None = None,symptom_onset: str | None = None, evidence: list[dict[str, str]] | None = None, recommended_actions: list[dict[str, str]] | None = None,) -> dict[str, Any]:
    errors: list[str] = []
    root_causes = root_causes or []
    affected_entities = affected_entities or []

    if incident_detected and not root_causes:
        errors.append("при incident_detected=true требуется минимум одна запись в root_causes")

    if not incident_detected and root_causes:
        errors.append("при incident_detected=false список root_causes должен быть пуст")

    for i, rc in enumerate(root_causes):
        if rc.get("entity_type") not in ENTITY_TYPES:
            errors.append(f"root_causes[{i}].entity_type должен быть одним из {sorted(ENTITY_TYPES)}")

        if rc.get("cause_class") not in CAUSE_CLASSES:
            errors.append(f"root_causes[{i}].cause_class должен быть одним из {sorted(CAUSE_CLASSES)}")

        if not rc.get("entity_id"):
            errors.append(f"root_causes[{i}].entity_id обязателен")

    for i, ae in enumerate(affected_entities):
        if ae.get("entity_type") not in ENTITY_TYPES:
            errors.append(f"affected_entities[{i}].entity_type недопустим")

    if confidence is not None and not 0.0 <= confidence <= 1.0:
        errors.append("confidence должен быть в диапазоне [0, 1]")

    if errors:
        return {"accepted": False, "errors": errors, "entity_types": sorted(ENTITY_TYPES), "cause_classes": sorted(CAUSE_CLASSES)}

    payload = {"run_id": cfg.run_id, "scenario_id": cfg.scenario_id, "ablation": cfg.ablation.name, "submitted_at": datetime.now(timezone.utc).isoformat(), "incident_detected": incident_detected,
               "confidence": confidence, "symptom_onset": symptom_onset, "root_causes": root_causes, "affected_entities": affected_entities, "evidence": evidence or [], "recommended_actions": recommended_actions or [],}

    path = cfg.audit_path / f"{cfg.run_id}.diagnosis.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    audit.record(tool="submit_diagnosis", group="answer", diagnosis=payload)

    return {"accepted": True, "stored_at": str(path), "note": "диагноз зафиксирован"}

_WRITE = re.compile(r"\b(insert|update|delete|truncate|drop|alter|create|grant|revoke|copy|" r"vacuum|analyze|reindex|cluster|call|do|refresh|set|reset|begin|commit)\b",re.IGNORECASE,)

ALLOWED_PARAMETERS = {"work_mem", "maintenance_work_mem", "max_wal_size", "checkpoint_completion_target", "autovacuum_vacuum_cost_limit", "autovacuum_vacuum_cost_delay", "autovacuum_naptime",
                      "default_statistics_target", "random_page_cost", "effective_io_concurrency", "hot_standby_feedback", "log_min_duration_statement",}

PROTECTED_APPS = {"pgmon_collector", "pgmon_mcp_reader", "walsender", "walreceiver"}