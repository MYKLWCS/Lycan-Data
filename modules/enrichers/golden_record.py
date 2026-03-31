"""
Golden Record Construction.

When the 4-pass pipeline identifies a cluster of duplicate records,
this module merges them into a single authoritative "golden record"
with full field-level provenance.

Source priority (higher = more trustworthy):
  government > credit_bureau > commercial > social > web_scrape

Merge rules:
  - Single-value fields (name, SSN, EIN): highest-priority source wins.
  - Multi-value fields (email, phone): keep all unique, ordered by priority.
  - Address / location: keep full history, most recent as primary.
  - Dates: most recent wins for last_seen; earliest wins for DOB.
  - Scores / flags: max across sources.

Every merged field carries provenance metadata:
  - winning source, all contributing sources, timestamps.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ── Source priority ──────────────────────────────────────────────────────────

SOURCE_PRIORITY: dict[str, int] = {
    "ssn_administration": 100,
    "state_government": 95,
    "federal_government": 90,
    "government": 90,
    "credit_bureau": 85,
    "corporate_registry": 80,
    "commercial_database": 70,
    "commercial": 70,
    "property_records": 65,
    "court_records": 60,
    "social_media": 40,
    "social": 40,
    "public_web_scrape": 20,
    "web_scrape": 20,
    "user_generated": 10,
    "unknown": 5,
}


def source_rank(source: str | None) -> int:
    if not source:
        return SOURCE_PRIORITY["unknown"]
    return SOURCE_PRIORITY.get(source.lower(), SOURCE_PRIORITY["unknown"])


# ── Data structures ──────────────────────────────────────────────────────────


@dataclass
class FieldProvenance:
    """Tracks where a merged field value came from."""

    field: str
    value: Any
    winning_source: str
    winning_timestamp: str | None
    all_sources: list[str]
    all_values: list[Any]
    conflict: bool = False  # True if sources disagreed


@dataclass
class GoldenRecord:
    """The merged canonical record with full provenance."""

    canonical_id: str
    merged_ids: list[str]
    merged_at: str
    fields: dict[str, Any]
    provenance: dict[str, FieldProvenance]
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_id": self.canonical_id,
            "merged_ids": self.merged_ids,
            "merged_at": self.merged_at,
            "confidence": self.confidence,
            "fields": self.fields,
            "provenance": {
                k: {
                    "field": v.field,
                    "value": v.value,
                    "winning_source": v.winning_source,
                    "all_sources": v.all_sources,
                    "conflict": v.conflict,
                }
                for k, v in self.provenance.items()
            },
        }


# ── Builder ──────────────────────────────────────────────────────────────────


# Fields where highest-priority single value wins
SINGLE_VALUE_FIELDS = {
    "full_name",
    "date_of_birth",
    "gender",
    "nationality",
    "primary_language",
    "place_of_birth",
    "country_of_birth",
    "religion",
    "ethnicity",
    "marital_status",
    "bio",
    "profile_image_url",
}

# Fields where we keep all unique values
MULTI_VALUE_FIELDS = {
    "emails",
    "phones",
    "citizenship_countries",
    "languages_spoken",
}

# Numeric fields where max wins
MAX_VALUE_FIELDS = {
    "estimated_net_worth_usd",
    "estimated_annual_income_usd",
    "property_count",
    "vehicle_count",
    "aircraft_count",
    "vessel_count",
    "adverse_media_count",
    "number_of_children",
}

# Boolean fields where True wins (any source says True → True)
ANY_TRUE_FIELDS = {
    "pep_status",
    "is_sanctioned",
    "is_deceased",
}


class GoldenRecordBuilder:
    """
    Merge duplicate person records into a canonical golden record.

    Usage:
        builder = GoldenRecordBuilder()
        golden = builder.build(records, canonical_id="abc-123")
    """

    def build(
        self,
        records: list[dict[str, Any]],
        canonical_id: str,
    ) -> GoldenRecord:
        """
        Merge a list of person-shaped dicts into a GoldenRecord.

        Each dict should have field values plus optional:
          _source: str (e.g. "credit_bureau")
          _timestamp: str (ISO 8601)
          _record_id: str
        """
        if not records:
            return GoldenRecord(
                canonical_id=canonical_id,
                merged_ids=[],
                merged_at=datetime.now(UTC).isoformat(),
                fields={},
                provenance={},
            )

        merged_fields: dict[str, Any] = {}
        provenance: dict[str, FieldProvenance] = {}
        merged_ids = [str(r.get("_record_id", r.get("id", ""))) for r in records]

        # Collect all fields across all records
        all_field_names: set[str] = set()
        for r in records:
            all_field_names.update(k for k in r if not k.startswith("_") and k not in ("id",))

        for field_name in all_field_names:
            candidates = self._collect_candidates(records, field_name)
            if not candidates:
                continue

            if field_name in SINGLE_VALUE_FIELDS:
                value, prov = self._merge_single_value(field_name, candidates)
            elif field_name in MULTI_VALUE_FIELDS:
                value, prov = self._merge_multi_value(field_name, candidates)
            elif field_name in MAX_VALUE_FIELDS:
                value, prov = self._merge_max_value(field_name, candidates)
            elif field_name in ANY_TRUE_FIELDS:
                value, prov = self._merge_any_true(field_name, candidates)
            else:
                # Default: single-value by priority
                value, prov = self._merge_single_value(field_name, candidates)

            if value is not None:
                merged_fields[field_name] = value
                provenance[field_name] = prov

        golden = GoldenRecord(
            canonical_id=canonical_id,
            merged_ids=merged_ids,
            merged_at=datetime.now(UTC).isoformat(),
            fields=merged_fields,
            provenance=provenance,
        )
        return golden

    def _collect_candidates(
        self,
        records: list[dict[str, Any]],
        field_name: str,
    ) -> list[dict[str, Any]]:
        """Gather all non-null values for a field across records."""
        candidates = []
        for r in records:
            val = r.get(field_name)
            if val is None:
                continue
            candidates.append(
                {
                    "value": val,
                    "source": r.get("_source", "unknown"),
                    "timestamp": r.get("_timestamp", ""),
                    "priority": source_rank(r.get("_source")),
                }
            )
        return candidates

    def _merge_single_value(
        self,
        field_name: str,
        candidates: list[dict[str, Any]],
    ) -> tuple[Any, FieldProvenance]:
        """Highest-priority source wins."""
        candidates.sort(key=lambda c: c["priority"], reverse=True)
        best = candidates[0]
        unique_values = set(str(c["value"]) for c in candidates)
        return best["value"], FieldProvenance(
            field=field_name,
            value=best["value"],
            winning_source=best["source"],
            winning_timestamp=best["timestamp"],
            all_sources=[c["source"] for c in candidates],
            all_values=[c["value"] for c in candidates],
            conflict=len(unique_values) > 1,
        )

    def _merge_multi_value(
        self,
        field_name: str,
        candidates: list[dict[str, Any]],
    ) -> tuple[list[Any], FieldProvenance]:
        """Keep all unique values, ordered by source priority."""
        candidates.sort(key=lambda c: c["priority"], reverse=True)
        seen: set[str] = set()
        unique_vals: list[Any] = []
        for c in candidates:
            val = c["value"]
            # Handle list-typed values (e.g. citizenship_countries)
            if isinstance(val, list):
                for item in val:
                    key = str(item).lower().strip()
                    if key not in seen:
                        seen.add(key)
                        unique_vals.append(item)
            else:
                key = str(val).lower().strip()
                if key not in seen:
                    seen.add(key)
                    unique_vals.append(val)

        return unique_vals, FieldProvenance(
            field=field_name,
            value=unique_vals,
            winning_source=candidates[0]["source"],
            winning_timestamp=candidates[0]["timestamp"],
            all_sources=[c["source"] for c in candidates],
            all_values=[c["value"] for c in candidates],
            conflict=False,
        )

    def _merge_max_value(
        self,
        field_name: str,
        candidates: list[dict[str, Any]],
    ) -> tuple[Any, FieldProvenance]:
        """Take the maximum numeric value."""
        best = max(candidates, key=lambda c: c["value"] or 0)
        return best["value"], FieldProvenance(
            field=field_name,
            value=best["value"],
            winning_source=best["source"],
            winning_timestamp=best["timestamp"],
            all_sources=[c["source"] for c in candidates],
            all_values=[c["value"] for c in candidates],
            conflict=len(set(c["value"] for c in candidates)) > 1,
        )

    def _merge_any_true(
        self,
        field_name: str,
        candidates: list[dict[str, Any]],
    ) -> tuple[bool, FieldProvenance]:
        """True if any source says True."""
        result = any(c["value"] for c in candidates)
        # For provenance, prefer the highest-priority source that said True
        true_cands = [c for c in candidates if c["value"]]
        if true_cands:
            true_cands.sort(key=lambda c: c["priority"], reverse=True)
            best = true_cands[0]
        else:
            candidates.sort(key=lambda c: c["priority"], reverse=True)
            best = candidates[0]

        return result, FieldProvenance(
            field=field_name,
            value=result,
            winning_source=best["source"],
            winning_timestamp=best["timestamp"],
            all_sources=[c["source"] for c in candidates],
            all_values=[c["value"] for c in candidates],
            conflict=len(set(c["value"] for c in candidates)) > 1,
        )


# ── Database-level golden record merge ───────────────────────────────────────


async def build_golden_record_from_cluster(
    session: AsyncSession,
    record_ids: list[str],
    canonical_id: str | None = None,
) -> GoldenRecord:
    """
    Load Person rows from DB, merge into a golden record, and apply
    the result to the canonical Person row.

    If canonical_id is not provided, the record with the most populated
    fields is chosen as canonical.
    """
    from shared.models.identifier import Identifier
    from shared.models.person import Person

    if len(record_ids) < 2:
        raise ValueError("Need at least 2 records to merge")

    # Load persons
    stmt = select(Person).where(Person.id.in_(record_ids))
    result = await session.execute(stmt)
    persons = result.scalars().all()

    if len(persons) < 2:
        raise ValueError(f"Only found {len(persons)} of {len(record_ids)} records")

    # Load identifiers for all
    ident_stmt = select(Identifier).where(Identifier.person_id.in_(record_ids))
    ident_result = await session.execute(ident_stmt)
    all_idents = ident_result.scalars().all()

    ident_map: dict[str, dict[str, list[str]]] = {}
    for ident in all_idents:
        pid = str(ident.person_id)
        val = ident.normalized_value or ident.value or ""
        ident_map.setdefault(pid, {"phones": [], "emails": [], "other": []})
        if ident.type == "phone":
            ident_map[pid]["phones"].append(val)
        elif ident.type == "email":
            ident_map[pid]["emails"].append(val)

    # Convert to dicts
    def _person_to_dict(p: Any) -> dict[str, Any]:
        pid = str(p.id)
        im = ident_map.get(pid, {})
        return {
            "id": pid,
            "_record_id": pid,
            "_source": p.scraped_from or "unknown",
            "_timestamp": p.last_scraped_at.isoformat() if p.last_scraped_at else "",
            "full_name": p.full_name,
            "date_of_birth": str(p.date_of_birth) if p.date_of_birth else None,
            "gender": p.gender,
            "nationality": p.nationality,
            "primary_language": p.primary_language,
            "bio": p.bio,
            "profile_image_url": p.profile_image_url,
            "place_of_birth": p.place_of_birth,
            "country_of_birth": p.country_of_birth,
            "citizenship_countries": p.citizenship_countries or [],
            "languages_spoken": p.languages_spoken or [],
            "religion": p.religion,
            "ethnicity": p.ethnicity,
            "marital_status": p.marital_status,
            "number_of_children": p.number_of_children,
            "estimated_net_worth_usd": p.estimated_net_worth_usd,
            "estimated_annual_income_usd": p.estimated_annual_income_usd,
            "wealth_tier": p.wealth_tier,
            "property_count": p.property_count,
            "vehicle_count": p.vehicle_count,
            "aircraft_count": p.aircraft_count,
            "vessel_count": p.vessel_count,
            "pep_status": p.pep_status,
            "is_sanctioned": p.is_sanctioned,
            "is_deceased": p.is_deceased,
            "adverse_media_count": p.adverse_media_count,
            "phones": im.get("phones", []),
            "emails": im.get("emails", []),
        }

    person_dicts = [_person_to_dict(p) for p in persons]

    # Choose canonical: most populated fields
    if canonical_id is None:

        def _field_count(d: dict) -> int:
            return sum(1 for k, v in d.items() if not k.startswith("_") and v is not None)

        person_dicts.sort(key=_field_count, reverse=True)
        canonical_id = person_dicts[0]["id"]

    builder = GoldenRecordBuilder()
    golden = builder.build(person_dicts, canonical_id=canonical_id)

    # Apply golden record fields to canonical Person row
    canonical_person = await session.get(Person, canonical_id)
    if canonical_person is None:
        raise ValueError(f"Canonical person {canonical_id} not found")

    for field_name, value in golden.fields.items():
        if hasattr(canonical_person, field_name) and value is not None:
            setattr(canonical_person, field_name, value)

    # Store provenance in meta
    meta = dict(canonical_person.meta or {})
    meta["golden_record"] = {
        "merged_ids": golden.merged_ids,
        "merged_at": golden.merged_at,
        "provenance": {
            k: {
                "winning_source": v.winning_source,
                "all_sources": v.all_sources,
                "conflict": v.conflict,
            }
            for k, v in golden.provenance.items()
        },
    }
    canonical_person.meta = meta

    await session.flush()
    logger.info(
        "GoldenRecord: merged %d records into canonical %s",
        len(record_ids),
        canonical_id,
    )
    return golden
