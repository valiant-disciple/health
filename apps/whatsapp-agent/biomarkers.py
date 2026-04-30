"""Biomarker registry: load supported_biomarkers.json once, expose lookup helpers.

Used at runtime to:
  - Map a raw test name (from OCR) to our canonical LOINC + tier
  - Decide if a result is fully interpretable (tier 1), specialist-deferred (tier 2),
    or part of a hard-blocked report type
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import structlog

log = structlog.get_logger()

DATA_PATH = Path(__file__).parent / "data" / "supported_biomarkers.json"


@dataclass(frozen=True)
class Biomarker:
    loinc: str
    name: str
    full_name: str
    aliases: tuple[str, ...]
    category: str
    organ_system: str | None
    tier: int
    specialist: str | None
    common_units: tuple[str, ...]
    ref_range_general: str | None
    ref_range_male: str | None
    ref_range_female: str | None
    critical_low: float | None
    critical_high: float | None
    what_it_measures: str | None
    clinical_significance: str | None
    fasting_required: bool

    def all_names(self) -> list[str]:
        names = [self.name, self.full_name] + list(self.aliases)
        return list({n.lower() for n in names if n})


@dataclass(frozen=True)
class BiomarkerRegistry:
    biomarkers: tuple[Biomarker, ...]
    blocked_report_keywords: tuple[str, ...]

    def __post_init__(self) -> None:
        # Build alias → biomarker index for O(1) exact-match lookup
        idx: dict[str, Biomarker] = {}
        for b in self.biomarkers:
            for alias in b.all_names():
                idx[_normalize(alias)] = b
        object.__setattr__(self, "_alias_index", idx)

    def by_loinc(self, loinc: str) -> Biomarker | None:
        for b in self.biomarkers:
            if b.loinc == loinc:
                return b
        return None

    def match(self, raw_name: str) -> Biomarker | None:
        """Best-effort match. Tries:
          1. Exact (case-insensitive, normalized) alias lookup
          2. Substring containment (raw contains alias OR alias contains raw, len ≥ 4)
        Returns the highest-tier match if multiple substring matches exist.
        """
        if not raw_name:
            return None
        norm = _normalize(raw_name)
        idx: dict[str, Biomarker] = self._alias_index  # type: ignore[attr-defined]
        if norm in idx:
            return idx[norm]
        # substring fallback
        candidates: list[Biomarker] = []
        for b in self.biomarkers:
            for alias in b.all_names():
                a = _normalize(alias)
                if len(a) < 4:
                    continue
                if a in norm or (norm in a and len(norm) >= 4):
                    candidates.append(b)
                    break
        if not candidates:
            return None
        # Prefer tier 1 over tier 2 if equally substring-matched
        candidates.sort(key=lambda b: (b.tier, -len(b.name)))
        return candidates[0]

    def is_report_blocked(self, raw_text: str) -> tuple[bool, str | None]:
        """Detect document-level hard-block keywords (genetic, pathology, imaging, etc.)."""
        if not raw_text:
            return False, None
        lower = raw_text.lower()
        for kw in self.blocked_report_keywords:
            if kw in lower:
                return True, kw
        return False, None


def _normalize(s: str) -> str:
    """Lowercase, strip whitespace, remove parenthetical, collapse spaces."""
    s = s.lower().strip()
    s = re.sub(r"\s*\([^)]*\)\s*", " ", s)  # drop "(SGPT)" suffixes
    s = re.sub(r"[^\w\s%/-]", " ", s)        # keep alnum, %, /, -
    s = re.sub(r"\s+", " ", s).strip()
    return s


@lru_cache(maxsize=1)
def get_registry() -> BiomarkerRegistry:
    with DATA_PATH.open() as f:
        payload = json.load(f)

    bms = tuple(
        Biomarker(
            loinc=b["loinc"],
            name=b["name"],
            full_name=b.get("full_name") or b["name"],
            aliases=tuple(b.get("aliases", [])),
            category=b.get("category", "unknown"),
            organ_system=b.get("organ_system"),
            tier=int(b.get("tier", 2)),
            specialist=b.get("specialist"),
            common_units=tuple(b.get("common_units", [])),
            ref_range_general=b.get("ref_range_general"),
            ref_range_male=b.get("ref_range_male"),
            ref_range_female=b.get("ref_range_female"),
            critical_low=b.get("critical_low"),
            critical_high=b.get("critical_high"),
            what_it_measures=b.get("what_it_measures"),
            clinical_significance=b.get("clinical_significance"),
            fasting_required=bool(b.get("fasting_required", False)),
        )
        for b in payload["biomarkers"]
    )
    blocked = tuple(payload.get("blocked_report_keywords", []))

    log.info("biomarkers.loaded", count=len(bms), blocked_keywords=len(blocked))
    return BiomarkerRegistry(biomarkers=bms, blocked_report_keywords=blocked)
