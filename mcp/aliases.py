from __future__ import annotations
from datetime import datetime
from typing import Any

SOURCE = "query_alias"

class AliasMap:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self._by_alias: dict[str, dict[str, Any]] = {}
        self._by_queryid: dict[str, str] = {}

        for row in rows or []:
            alias = row["alias"]
            self._by_alias[alias] = row
            self._by_queryid[str(row["queryid"])] = alias

    def alias(self, queryid: Any) -> str:
        return self._by_queryid.get(str(queryid), f"Q?{queryid}")

    def queryid(self, alias: str) -> Any | None:
        row = self._by_alias.get(alias.upper())
        return row["queryid"] if row else None

    def entry(self, alias: str) -> dict[str, Any] | None:
        return self._by_alias.get(alias.upper())

    def text(self, alias: str) -> str | None:
        row = self.entry(alias)
        return row.get("normalized") if row else None

    def __len__(self) -> int:
        return len(self._by_alias)

async def load_aliases(backend, at: datetime) -> AliasMap:
    rows = await backend.snapshot_at(SOURCE, at)
    return AliasMap(rows)

def next_alias(existing: int) -> str:
    return f"Q{existing + 1:02d}"