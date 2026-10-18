"""Parliament names (body keys such as CHE, BE or 261) from the OpenParlData bodies export."""

from __future__ import annotations

import gzip
import json
from pathlib import Path


def load_parliaments(path: Path) -> dict[str, dict[str, str | None]]:
    """Every body that has a parliament, by key. Empty if the export is not downloaded."""
    if not path.exists():
        return {}
    parliaments: dict[str, dict[str, str | None]] = {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if row.get("has_parliament") is not True:
                continue
            parliaments[row["body_key"]] = {
                "name": row.get("name_de") or row.get("name"),
                "name_fr": row.get("name_fr"),
                "type": row.get("type"),
                "canton": row.get("canton_key"),
            }
    return parliaments
