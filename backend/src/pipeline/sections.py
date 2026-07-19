from __future__ import annotations

import re

_ITEM_RE = re.compile(r"^\s*item\s+(\d{1,2}[a-c]?)\b", re.IGNORECASE)
_PART_RE = re.compile(r"^\s*part\s+(iv|i{1,3})\b", re.IGNORECASE)
_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4}
_MAX_HEADING_LEN = 120


class SectionTracker:
    """State machine: feed block texts in document order, get each block's section label."""

    def __init__(self, form_type: str):
        self._is_10q = form_type == "10-Q"
        self._part: int | None = None
        self.current = "other"

    def update(self, block_text: str) -> str:
        text = block_text.strip()
        if len(text) <= _MAX_HEADING_LEN:
            part = _PART_RE.match(text)
            if part:
                self._part = _ROMAN[part.group(1).lower()]
                return self.current
            item = _ITEM_RE.match(text)
            if item:
                label = f"item{item.group(1).lower()}"
                if self._is_10q and self._part:
                    label = f"part{self._part}.{label}"
                self.current = label
        return self.current
