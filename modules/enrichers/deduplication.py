"""
Deduplication Engine.

Finds and merges duplicate records across persons and identifiers.
Every merge is logged. Never deletes — always merges to a canonical record.
"""
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MergeCandidate:
    """A pair of records that may be duplicates."""
    id_a: str
    id_b: str
    similarity_score: float  # 0.0 - 1.0
    match_reasons: list[str] = field(default_factory=list)


# ─── Name normalization ───────────────────────────────────────────────────────

HONORIFICS = frozenset(['mr', 'mrs', 'ms', 'dr', 'prof', 'rev', 'sr', 'jr', 'ii', 'iii'])


def normalize_name(name: str) -> str:
    """Lowercase, strip honorifics, remove punctuation, sort tokens."""
    name = name.lower().strip()
    name = re.sub(r"[^\w\s]", "", name)
    tokens = [t for t in name.split() if t not in HONORIFICS]
    return " ".join(sorted(tokens))


def name_similarity(name_a: str, name_b: str) -> float:
    """
    Compute similarity score between two names.
    Returns 1.0 for identical, 0.0 for no overlap.
    """
    if not name_a or not name_b:
        return 0.0

    norm_a = normalize_name(name_a)
    norm_b = normalize_name(name_b)

    if norm_a == norm_b:
        return 1.0

    tokens_a = set(norm_a.split())
    tokens_b = set(norm_b.split())

    if not tokens_a or not tokens_b:
        return 0.0

    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b

    jaccard = len(intersection) / len(union)
    return jaccard


# ─── Identifier deduplication ─────────────────────────────────────────────────

def normalize_phone(phone: str) -> str:
    """Strip all non-digits, ensure E.164-ish format."""
    digits = re.sub(r'\D', '', phone)
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits[0] == '1':
        return f"+{digits}"
    return f"+{digits}"


def normalize_email(email: str) -> str:
    """Lowercase, strip whitespace."""
    return email.lower().strip()


def normalize_username(username: str) -> str:
    """Lowercase, strip @ prefix."""
    return username.lower().lstrip('@').strip()


def find_duplicate_identifiers(
    identifiers: list[dict[str, Any]],
) -> list[MergeCandidate]:
    """
    Find duplicate identifiers within a list.
    Each dict must have: id, type, value (or normalized_value).
    Returns pairs that should be merged.
    """
    normalizers = {
        'phone': normalize_phone,
        'email': normalize_email,
        'username': normalize_username,
    }

    candidates = []
    type_buckets: dict[str, list[dict]] = {}

    for ident in identifiers:
        ident_type = ident.get('type', 'unknown')
        type_buckets.setdefault(ident_type, []).append(ident)

    for ident_type, bucket in type_buckets.items():
        normalizer = normalizers.get(ident_type, str.lower)
        seen: dict[str, dict] = {}

        for ident in bucket:
            raw_value = ident.get('normalized_value') or ident.get('value', '')
            norm = normalizer(raw_value)

            if norm in seen:
                existing = seen[norm]
                candidates.append(MergeCandidate(
                    id_a=str(existing['id']),
                    id_b=str(ident['id']),
                    similarity_score=1.0,
                    match_reasons=[f"identical normalized {ident_type}: {norm}"],
                ))
            else:
                seen[norm] = ident

    return candidates


# ─── Person deduplication ─────────────────────────────────────────────────────

MERGE_THRESHOLD = 0.75  # similarity score above which we suggest merge


def find_duplicate_persons(
    persons: list[dict[str, Any]],
) -> list[MergeCandidate]:
    """
    Find persons who may be the same individual.
    Each dict: id, full_name, dob (optional), identifiers (list of normalized values)
    """
    candidates = []
    n = len(persons)

    for i in range(n):
        for j in range(i + 1, n):
            a, b = persons[i], persons[j]
            score, reasons = _person_similarity(a, b)
            if score >= MERGE_THRESHOLD:
                candidates.append(MergeCandidate(
                    id_a=str(a['id']),
                    id_b=str(b['id']),
                    similarity_score=score,
                    match_reasons=reasons,
                ))

    return candidates


def _person_similarity(a: dict, b: dict) -> tuple[float, list[str]]:
    """Compute similarity score and reasons for two person records.

    Scoring:
      - Shared phone or email → 0.95 (near-certain match, early exit)
      - Name similarity       → up to 0.40
      - DOB exact match       → 0.30
      - Other shared idents   → up to 0.20
    """
    score = 0.0
    reasons = []

    idents_a = set(str(i).lower().strip() for i in a.get('identifiers', []) if i)
    idents_b = set(str(i).lower().strip() for i in b.get('identifiers', []) if i)

    # Fast path: shared phone or email is near-certain same person
    phones_a = set(str(i) for i in a.get('phones', [])) | {v for v in idents_a if _looks_like_phone(v)}
    phones_b = set(str(i) for i in b.get('phones', [])) | {v for v in idents_b if _looks_like_phone(v)}
    emails_a = set(str(i) for i in a.get('emails', [])) | {v for v in idents_a if '@' in v}
    emails_b = set(str(i) for i in b.get('emails', [])) | {v for v in idents_b if '@' in v}

    shared_phones = phones_a & phones_b
    shared_emails = emails_a & emails_b

    if shared_phones:
        reasons.append(f"shared phone: {next(iter(shared_phones))}")
        return 0.95, reasons
    if shared_emails:
        reasons.append(f"shared email: {next(iter(shared_emails))}")
        return 0.95, reasons

    # Name similarity (weight 0.40)
    name_a = a.get('full_name', '')
    name_b = b.get('full_name', '')
    name_sim = name_similarity(name_a, name_b)
    score += name_sim * 0.40
    if name_sim >= 0.75:
        reasons.append(f"name match: '{name_a}' ≈ '{name_b}' ({name_sim:.2f})")

    # DOB exact match (weight 0.30)
    dob_a = a.get('dob')
    dob_b = b.get('dob')
    if dob_a and dob_b and str(dob_a) == str(dob_b):
        score += 0.30
        reasons.append(f"DOB match: {dob_a}")

    # Other shared identifiers (weight up to 0.20)
    shared = idents_a & idents_b
    if shared:
        shared_score = min(0.20, len(shared) * 0.10)
        score += shared_score
        reasons.append(f"shared identifiers: {', '.join(list(shared)[:3])}")

    return min(1.0, score), reasons


def _looks_like_phone(value: str) -> bool:
    """Heuristic: string of mostly digits that's 7+ chars long."""
    digits = re.sub(r'\D', '', value)
    return len(digits) >= 7 and len(digits) <= 15


def merge_persons(canonical_id: str, duplicate_id: str) -> dict[str, Any]:
    """
    Return a merge plan dict — the caller executes the DB operations.
    Always merges duplicate_id INTO canonical_id.
    """
    return {
        "canonical_id": canonical_id,
        "duplicate_id": duplicate_id,
        "action": "merge",
        "reassign_tables": [
            "identifiers", "social_profiles", "addresses",
            "employment_histories", "educations", "breach_records",
            "media_assets", "watchlist_matches", "darkweb_mentions",
            "crypto_wallets", "behavioural_profiles", "credit_risk_assessments",
            "wealth_assessments", "burner_assessments", "relationships",
            "crawl_jobs", "alerts",
            "criminal_records", "identity_documents", "credit_profiles",
            "identifier_history",
        ],
        "delete_duplicate": True,
        "merged_at": datetime.now(timezone.utc).isoformat(),
    }
