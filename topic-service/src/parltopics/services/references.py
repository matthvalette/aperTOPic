"""Understands the links and ids people paste. Pure functions, no I/O."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class ReferenceKind(StrEnum):
    AFFAIR = "affair"  # OpenParlData affair id
    DOC = "doc"  # OpenParlData document id
    FILE = "file"  # raw file on files.openparldata.ch
    CURIA_VISTA = "curia_vista"  # federal affair by its Curia Vista id


@dataclass(frozen=True)
class Reference:
    kind: ReferenceKind
    value: str  # id or URL


_PATTERNS: list[tuple[re.Pattern[str], ReferenceKind]] = [
    (re.compile(r"openparldata\.ch/item/affairs/(\d+)"), ReferenceKind.AFFAIR),
    (re.compile(r"openparldata\.ch/item/docs/(\d+)"), ReferenceKind.DOC),
    (re.compile(r"api\.openparldata\.ch/v\d+/affairs/(\d+)"), ReferenceKind.AFFAIR),
    (re.compile(r"api\.openparldata\.ch/v\d+/docs/(\d+)"), ReferenceKind.DOC),
    (re.compile(r"parlament\.ch/.*[?&]AffairId=(\d+)", re.I), ReferenceKind.CURIA_VISTA),
]
_FILE = re.compile(r"^https?://files\.openparldata\.ch/doc/\S+$")


def parse_reference(value: str) -> Reference:
    """Accepts, for example:

    - https://openparldata.ch/item/affairs/70435
    - https://api.openparldata.ch/v1/affairs/70435/texts
    - https://api.openparldata.ch/v1/docs/927844
    - https://files.openparldata.ch/doc/SZ/553bfb4a92...
    - https://www.parlament.ch/de/ratsbetrieb/suche-curia-vista/geschaeft?AffairId=20243010
    - 70435 (an affair id), doc:927844
    """
    text = value.strip()
    if text.isdigit():
        return Reference(ReferenceKind.AFFAIR, text)
    prefixed = re.fullmatch(r"(affair|doc)[:#\s]*(\d+)", text, re.I)
    if prefixed:
        kind = ReferenceKind.AFFAIR if prefixed.group(1).lower() == "affair" else ReferenceKind.DOC
        return Reference(kind, prefixed.group(2))
    for pattern, kind in _PATTERNS:
        match = pattern.search(text)
        if match:
            return Reference(kind, match.group(1))
    if _FILE.match(text):
        return Reference(ReferenceKind.FILE, text)
    raise ValueError(
        "Not an OpenParlData link or id. Paste an openparldata.ch or api.openparldata.ch link, "
        "a files.openparldata.ch document link, a Curia Vista link, or an affair id."
    )
