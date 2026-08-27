"""
Taxi-domain template / slot matcher for TTS caching.

Matches normalized spoken clauses against a small configurable registry.
Only templates that preserve meaning are used; unmatched clauses fall through
to whole-clause caching (never word-by-word stitching).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from config import TAXI_TEMPLATES_PATH

logger = logging.getLogger("server.templates")


@dataclass(frozen=True)
class SynthUnit:
    """One speakable unit large enough to preserve natural prosody."""

    text: str
    kind: str  # "clause" | "static" | "dynamic"
    template_id: str | None = None
    slot_name: str | None = None


@dataclass
class TemplateMatch:
    template_id: str
    slots: dict[str, str]
    units: list[SynthUnit] = field(default_factory=list)


class TemplateRegistry:
    def __init__(self, path: Path | None = None):
        self.path = path or TAXI_TEMPLATES_PATH
        self.version = "0"
        self._compiled: list[tuple[str, re.Pattern[str], list[str], list[dict]]] = []
        self.reload()

    def reload(self) -> None:
        self._compiled.clear()
        if not self.path.exists():
            logger.warning("Taxi templates missing at %s", self.path)
            self.version = "0"
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.version = str(raw.get("version", "1"))
        for item in raw.get("templates", []):
            tid = item["id"]
            pattern = re.compile(item["pattern"])
            slots = list(item.get("slots") or [])
            units = list(item.get("units") or [])
            self._compiled.append((tid, pattern, slots, units))
        logger.info("Loaded %d taxi TTS templates (v%s)", len(self._compiled), self.version)

    def match(self, clause: str) -> TemplateMatch | None:
        text = (clause or "").strip()
        if not text:
            return None
        for tid, pattern, slot_names, unit_defs in self._compiled:
            m = pattern.match(text)
            if not m:
                continue
            slots = {k: (m.groupdict().get(k) or "").strip() for k in slot_names}
            if any(not v for v in slots.values()):
                # Incomplete capture — refuse rather than risk wrong audio
                continue
            units = self._build_units(tid, slots, unit_defs, text)
            if not units:
                continue
            # Guard: every slot value must appear in some dynamic unit text
            if slots and not self._slots_represented(slots, units):
                logger.debug("Template %s rejected: slot not represented in units", tid)
                continue
            return TemplateMatch(template_id=tid, slots=slots, units=units)
        return None

    @staticmethod
    def _slots_represented(slots: dict[str, str], units: list[SynthUnit]) -> bool:
        dyn = " ".join(u.text for u in units if u.kind == "dynamic").lower()
        return all(v.lower() in dyn for v in slots.values() if v)

    @staticmethod
    def _build_units(
        tid: str,
        slots: dict[str, str],
        unit_defs: list[dict],
        fallback_text: str,
    ) -> list[SynthUnit]:
        if not unit_defs:
            return [SynthUnit(text=fallback_text, kind="clause", template_id=tid)]
        out: list[SynthUnit] = []
        for ud in unit_defs:
            utype = ud.get("type", "static")
            if utype == "static":
                t = (ud.get("text") or "").strip()
                if t:
                    out.append(SynthUnit(text=t, kind="static", template_id=tid))
            elif utype == "dynamic":
                fmt = ud.get("format") or ""
                try:
                    t = fmt.format(**slots).strip()
                except KeyError:
                    return []
                if not t:
                    return []
                # Identify primary slot for metrics (first placeholder name)
                slot_name = None
                for name in slots:
                    if f"{{{name}}}" in fmt:
                        slot_name = name
                        break
                out.append(
                    SynthUnit(
                        text=t,
                        kind="dynamic",
                        template_id=tid,
                        slot_name=slot_name,
                    )
                )
            else:
                return []
        return out

    def decompose(self, clause: str) -> list[SynthUnit]:
        """Return template units or a single whole-clause unit."""
        m = self.match(clause)
        if m is not None:
            return m.units
        text = (clause or "").strip()
        if not text:
            return []
        return [SynthUnit(text=text, kind="clause")]

    def decompose_many(self, clauses: Iterable[str]) -> list[SynthUnit]:
        units: list[SynthUnit] = []
        for c in clauses:
            units.extend(self.decompose(c))
        return units


_REGISTRY: TemplateRegistry | None = None


def get_template_registry(path: Path | None = None) -> TemplateRegistry:
    global _REGISTRY
    if _REGISTRY is None or (path is not None and path != _REGISTRY.path):
        _REGISTRY = TemplateRegistry(path)
    return _REGISTRY
