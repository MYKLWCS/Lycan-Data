"""
Deduplication Engine.

Finds and merges duplicate records across persons and identifiers.
Every merge is logged. Never deletes — always merges to a canonical record.
"""
import hashlib
import logging
import math
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


# ─── ExactMatchDeduplicator — Pass 1 ─────────────────────────────────────────

class ExactMatchDeduplicator:
    """Pass 1 exact-match deduplication using composite deterministic keys."""

    def __init__(self, dragonfly_client=None):
        # dragonfly_client: Redis-compatible client, or None for in-memory fallback
        self.dragonfly = dragonfly_client
        self.seen_hashes: set[str] = set()

    def normalize_string(self, s: str) -> str:
        """Lowercase, strip whitespace, remove . , - """
        return re.sub(r'[.,\-]', '', s.lower().strip())

    def extract_ssn_last4(self, ssn: str) -> str:
        """Extract last 4 digits from SSN string."""
        digits = re.sub(r'\D', '', ssn)
        return digits[-4:] if len(digits) >= 4 else digits

    def create_composite_keys(self, record: dict) -> list[tuple[str, int]]:
        """
        Returns list of (key_string, priority) tuples.
        Priority 1 (strongest): f"ssn:{ssn_last4}:{dob}:{name}"
        Priority 2: f"email:{email}"  (only if @ present and non-empty)
        Priority 3: f"phone:{phone}"  (only if 10+ digits after normalizing)
        Priority 4: f"namedob:{name}:{dob}"  (only if both non-empty)
        Priority 5: f"ein:{ein}"  (only if non-empty, for businesses)
        """
        keys: list[tuple[str, int]] = []

        raw_ssn = record.get('ssn', '') or ''
        raw_dob = record.get('dob', '') or ''
        raw_name = record.get('full_name', '') or ''
        raw_email = record.get('email', '') or ''
        raw_phone = record.get('phone', '') or ''
        raw_ein = record.get('ein', '') or ''

        ssn_last4 = self.extract_ssn_last4(raw_ssn)
        dob = self.normalize_string(str(raw_dob))
        name = self.normalize_string(raw_name)

        # Priority 1: SSN last4 + DOB + name
        if ssn_last4 and dob and name:
            keys.append((f"ssn:{ssn_last4}:{dob}:{name}", 1))

        # Priority 2: email (only if contains @ and non-empty)
        email = self.normalize_string(raw_email)
        if email and '@' in email:
            keys.append((f"email:{email}", 2))

        # Priority 3: phone (only if 10+ digits after normalizing)
        phone_digits = re.sub(r'\D', '', raw_phone)
        if len(phone_digits) >= 10:
            keys.append((f"phone:{phone_digits}", 3))

        # Priority 4: name + dob (only if both non-empty)
        if name and dob:
            keys.append((f"namedob:{name}:{dob}", 4))

        # Priority 5: EIN (only if non-empty, for businesses)
        ein = self.normalize_string(raw_ein)
        if ein:
            keys.append((f"ein:{ein}", 5))

        return keys

    def hash_key(self, key: str) -> str:
        """SHA256 hex digest of key."""
        return hashlib.sha256(key.encode('utf-8')).hexdigest()

    def check_and_mark_duplicate(self, record: dict) -> tuple[bool, str]:
        """
        Check each composite key hash. If found in dragonfly/seen_hashes → return (True, key).
        Otherwise mark all keys as seen. Return (False, "").
        Dragonfly: use setex with TTL 86400 under key f"dedup:key:{hash}"
        """
        composite_keys = self.create_composite_keys(record)
        # Sort by priority so we check strongest signals first
        composite_keys.sort(key=lambda t: t[1])

        for key_str, _priority in composite_keys:
            h = self.hash_key(key_str)

            if self.dragonfly is not None:
                # Atomic check-and-set: returns None if key already existed (duplicate)
                dragonfly_key = f"dedup:key:{h}"
                was_set = self.dragonfly.set(dragonfly_key, 1, ex=86400, nx=True)
                if was_set is None:
                    # Key already existed — this is a duplicate
                    return (True, key_str)
                # Key was newly set — not a duplicate, continue to next key
            else:
                if h in self.seen_hashes:
                    return True, key_str
                self.seen_hashes.add(h)

        return False, ""

    def process_batch(self, records: list) -> tuple[list, list]:
        """
        Returns (unique, duplicates).
        duplicates entries: {'record': record, 'matched_key': key, 'pass': 1}
        """
        unique: list = []
        duplicates: list = []

        for record in records:
            is_dup, matched_key = self.check_and_mark_duplicate(record)
            if is_dup:
                duplicates.append({'record': record, 'matched_key': matched_key, 'pass': 1})
            else:
                unique.append(record)

        return unique, duplicates


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


# ─── Soundex phonetic encoder ─────────────────────────────────────────────────

_SOUNDEX_TABLE: dict[str, str] = {
    'B': '1', 'F': '1', 'P': '1', 'V': '1',
    'C': '2', 'G': '2', 'J': '2', 'K': '2', 'Q': '2',
    'S': '2', 'X': '2', 'Y': '2', 'Z': '2',
    'D': '3', 'T': '3',
    'L': '4',
    'M': '5', 'N': '5',
    'R': '6',
}


def soundex(name: str) -> str:
    """US Soundex — maps phonetically similar names to same 4-char code."""
    if not name:
        return "0000"

    name = re.sub(r"[^A-Za-z]", "", name).upper()
    if not name:
        return "0000"

    first_letter = name[0]
    rest = name[1:]

    # Encode all characters (including first) then process
    coded = []
    prev_code = _SOUNDEX_TABLE.get(first_letter, '0')

    for ch in rest:
        code = _SOUNDEX_TABLE.get(ch, '0')
        if code != '0' and code != prev_code:
            coded.append(code)
        prev_code = code

    result = first_letter + "".join(coded)
    result = (result + "000")[:4]
    return result


# ─── String similarity functions ──────────────────────────────────────────────

def jaro_winkler_similarity(s1: str, s2: str) -> float:
    """
    Jaro-Winkler similarity between two strings.
    Pure Python. Winkler prefix boost: p=0.1, max prefix length=4.
    Returns a float in [0.0, 1.0].
    """
    if s1 == s2:
        return 1.0
    if not s1 or not s2:
        return 0.0

    len1 = len(s1)
    len2 = len(s2)

    match_distance = max(len1, len2) // 2 - 1
    match_distance = max(0, match_distance)

    s1_matches = [False] * len1
    s2_matches = [False] * len2

    matches = 0
    transpositions = 0

    # Find matching characters
    for i in range(len1):
        start = max(0, i - match_distance)
        end = min(i + match_distance + 1, len2)

        for j in range(start, end):
            if s2_matches[j] or s1[i] != s2[j]:
                continue
            s1_matches[i] = True
            s2_matches[j] = True
            matches += 1
            break

    if matches == 0:
        return 0.0

    # Count transpositions
    k = 0
    for i in range(len1):
        if not s1_matches[i]:
            continue
        while not s2_matches[k]:
            k += 1
        if s1[i] != s2[k]:
            transpositions += 1
        k += 1

    jaro = (
        matches / len1
        + matches / len2
        + (matches - transpositions / 2) / matches
    ) / 3.0

    # Winkler prefix boost (p=0.1, max prefix=4)
    prefix = 0
    for i in range(min(4, min(len1, len2))):
        if s1[i] == s2[i]:
            prefix += 1
        else:
            break

    return jaro + prefix * 0.1 * (1.0 - jaro)


def levenshtein_similarity(s1: str, s2: str) -> float:
    """
    Normalized Levenshtein similarity between two strings.
    Pure Python DP implementation.
    Returns 1 - edit_distance / max(len(s1), len(s2)).
    Returns 1.0 for identical strings, 0.0 if both are empty.
    """
    if s1 == s2:
        return 1.0

    len1 = len(s1)
    len2 = len(s2)

    if len1 == 0 and len2 == 0:
        return 1.0
    if len1 == 0 or len2 == 0:
        return 0.0

    # DP matrix — two rows suffice
    prev = list(range(len2 + 1))
    curr = [0] * (len2 + 1)

    for i in range(1, len1 + 1):
        curr[0] = i
        for j in range(1, len2 + 1):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            curr[j] = min(
                prev[j] + 1,        # deletion
                curr[j - 1] + 1,    # insertion
                prev[j - 1] + cost, # substitution
            )
        prev, curr = curr, prev

    edit_distance = prev[len2]
    return 1.0 - edit_distance / max(len1, len2)


# ─── FuzzyDeduplicator ────────────────────────────────────────────────────────

class FuzzyDeduplicator:
    """
    Blocking-based fuzzy deduplicator that reduces O(n²) comparisons
    by grouping persons into overlapping candidate buckets before scoring.
    """

    MERGE_THRESHOLD: float = 0.78

    def __init__(
        self,
        jaro_winkler_threshold: float = 0.92,
        levenshtein_threshold: float = 0.88,
        merge_threshold: float | None = None,
    ) -> None:
        """
        jaro_winkler_threshold: minimum JW score to count as name match
        levenshtein_threshold: minimum Lev score to count as address match
        merge_threshold: override for MERGE_THRESHOLD class default
        """
        self.jw_threshold = jaro_winkler_threshold
        self.lev_threshold = levenshtein_threshold
        if merge_threshold is not None:
            self.MERGE_THRESHOLD = merge_threshold

    def find_candidates(self, persons: list[dict]) -> list[MergeCandidate]:
        """
        Find merge candidates across a list of person dicts.
        Each dict: id, full_name, dob, phones, emails, identifiers, addresses.
        Returns candidates sorted by similarity_score descending.
        """
        # Build an inverted index: blocking_key → list of person indices
        buckets: dict[str, list[int]] = {}
        for idx, person in enumerate(persons):
            for key in self._blocking_keys(person):
                buckets.setdefault(key, []).append(idx)

        # Deduplicate pairs using a seen set
        seen_pairs: set[tuple[int, int]] = set()
        candidates: list[MergeCandidate] = []

        for _, indices in buckets.items():
            for i in range(len(indices)):
                for j in range(i + 1, len(indices)):
                    a_idx = indices[i]
                    b_idx = indices[j]
                    pair = (min(a_idx, b_idx), max(a_idx, b_idx))
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)

                    score, reasons = self._score_pair(persons[a_idx], persons[b_idx])
                    if score >= self.MERGE_THRESHOLD:
                        candidates.append(MergeCandidate(
                            id_a=str(persons[a_idx]['id']),
                            id_b=str(persons[b_idx]['id']),
                            similarity_score=score,
                            match_reasons=reasons,
                        ))

        candidates.sort(key=lambda c: c.similarity_score, reverse=True)
        return candidates

    def _blocking_keys(self, person: dict) -> list[str]:
        """
        Generate blocking keys for a person.
        A person is placed in every bucket whose key it matches;
        only persons sharing at least one bucket are compared.
        """
        keys: list[str] = []

        dob = person.get('dob')
        if dob:
            birth_year = str(dob)[:4]
            if birth_year.isdigit():
                keys.append(f"birth_year:{birth_year}")

        full_name = person.get('full_name', '')
        if full_name:
            parts = full_name.strip().split()
            # Use last token as a proxy for last name
            last_name = parts[-1] if parts else ''
            if last_name:
                keys.append(f"soundex:{soundex(last_name)}")

        phones = person.get('phones', [])
        for phone in phones:
            digits = re.sub(r'\D', '', str(phone))
            if len(digits) >= 3:
                keys.append(f"phone_prefix:{digits[:3]}")
                break  # one phone prefix per person is enough for blocking

        return keys

    def _score_pair(self, a: dict, b: dict) -> tuple[float, list[str]]:
        """
        Score a pair of persons and return (score, reasons).

        Weights:
          - Shared phone/email        → 0.95 (early exit)
          - Name similarity (JW)      × 0.40
          - DOB exact match           × 0.30
          - Shared other identifiers  × min(0.20, count × 0.10)
          - Address partial match     × 0.10
        """
        score = 0.0
        reasons: list[str] = []

        # ── Shared phone/email — early exit ──────────────────────────────────
        phones_a: set[str] = {
            re.sub(r'\D', '', str(p)) for p in a.get('phones', []) if p
        }
        phones_b: set[str] = {
            re.sub(r'\D', '', str(p)) for p in b.get('phones', []) if p
        }
        emails_a: set[str] = {str(e).lower().strip() for e in a.get('emails', []) if e}
        emails_b: set[str] = {str(e).lower().strip() for e in b.get('emails', []) if e}

        shared_phones = (phones_a & phones_b) - {''}
        shared_emails = (emails_a & emails_b) - {''}

        if shared_phones:
            reasons.append(f"shared phone: {next(iter(shared_phones))}")
            return 0.95, reasons
        if shared_emails:
            reasons.append(f"shared email: {next(iter(shared_emails))}")
            return 0.95, reasons

        # ── Name similarity (Jaro-Winkler) × 0.40 ────────────────────────────
        name_a = a.get('full_name', '')
        name_b = b.get('full_name', '')
        if name_a and name_b:
            jw = jaro_winkler_similarity(name_a.lower(), name_b.lower())
            score += jw * 0.40
            if jw >= self.jw_threshold:
                reasons.append(f"name JW match: '{name_a}' ≈ '{name_b}' ({jw:.2f})")

        # ── DOB exact match × 0.30 ────────────────────────────────────────────
        dob_a = a.get('dob')
        dob_b = b.get('dob')
        if dob_a and dob_b and str(dob_a) == str(dob_b):
            score += 0.30
            reasons.append(f"DOB match: {dob_a}")

        # ── Shared other identifiers × min(0.20, count × 0.10) ───────────────
        idents_a = {str(i).lower().strip() for i in a.get('identifiers', []) if i}
        idents_b = {str(i).lower().strip() for i in b.get('identifiers', []) if i}
        shared_idents = idents_a & idents_b
        if shared_idents:
            ident_score = min(0.20, len(shared_idents) * 0.10)
            score += ident_score
            reasons.append(f"shared identifiers: {', '.join(list(shared_idents)[:3])}")

        # ── Address partial match (levenshtein > 0.7 on city+state) × 0.10 ───
        addr_a = a.get('addresses', [])
        addr_b = b.get('addresses', [])
        if addr_a and addr_b:
            # Use first address from each person
            def _city_state(addr: Any) -> str:
                if isinstance(addr, dict):
                    city = str(addr.get('city', '')).lower().strip()
                    state = str(addr.get('state', '')).lower().strip()
                    return f"{city} {state}".strip()
                return str(addr).lower().strip()

            cs_a = _city_state(addr_a[0])
            cs_b = _city_state(addr_b[0])
            if cs_a and cs_b:
                lev = levenshtein_similarity(cs_a, cs_b)
                if lev > self.lev_threshold:
                    score += 0.10
                    reasons.append(f"address match: '{cs_a}' ≈ '{cs_b}' ({lev:.2f})")

        return min(1.0, score), reasons


# ─── BloomDedup ───────────────────────────────────────────────────────────────

class BloomDedup:
    """
    O(1) probabilistic deduplication using a simple Bloom filter.
    No external dependencies — uses stdlib hashlib (SHA256) with salted hashes.
    """

    def __init__(self, expected_n: int = 1_000_000, fp_rate: float = 0.001) -> None:
        m_bits, k_hashes = self._optimal_params(expected_n, fp_rate)
        self._m: int = m_bits
        self._k: int = k_hashes
        self._bits: bytearray = bytearray(math.ceil(m_bits / 8))

    def _optimal_params(self, n: int, p: float) -> tuple[int, int]:
        """
        Compute optimal Bloom filter parameters.
        m = -n * ln(p) / (ln(2)^2)  — number of bits
        k = (m / n) * ln(2)          — number of hash functions
        """
        ln2 = math.log(2)
        m = int(math.ceil(-n * math.log(p) / (ln2 ** 2)))
        k = int(round((m / n) * ln2))
        k = max(1, k)
        return m, k

    def _hashes(self, key: str) -> list[int]:
        """
        Generate k independent bit positions using SHA256 with integer salts.
        Each hash uses salt i prepended to the key to produce a different digest.
        """
        positions: list[int] = []
        encoded = key.encode('utf-8')
        for i in range(self._k):
            salt = i.to_bytes(4, 'little')
            digest = hashlib.sha256(salt + encoded).digest()
            # Take first 8 bytes as a 64-bit integer, then mod m
            pos = int.from_bytes(digest[:8], 'little') % self._m
            positions.append(pos)
        return positions

    def _set_bit(self, pos: int) -> None:
        byte_index = pos // 8
        bit_index = pos % 8
        self._bits[byte_index] |= (1 << bit_index)

    def _get_bit(self, pos: int) -> bool:
        byte_index = pos // 8
        bit_index = pos % 8
        return bool(self._bits[byte_index] & (1 << bit_index))

    def add(self, key: str) -> bool:
        """
        Add key to the filter.
        Returns True if the key was NEW (not seen before), False if it was already present.
        """
        if self.contains(key):
            return False
        for pos in self._hashes(key):
            self._set_bit(pos)
        return True

    def contains(self, key: str) -> bool:
        """Return True if the key is probably in the filter (may have false positives)."""
        return all(self._get_bit(pos) for pos in self._hashes(key))


# ─── AsyncMergeExecutor ───────────────────────────────────────────────────────

try:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy import text as sa_text
    _SQLALCHEMY_AVAILABLE = True
except ImportError:
    _SQLALCHEMY_AVAILABLE = False
    AsyncSession = Any  # type: ignore[misc,assignment]
    sa_text = None  # type: ignore[assignment]

import uuid as _uuid_mod
_SAFE_TABLE_RE = re.compile(r'^[a-z_][a-z0-9_]{1,62}$')


class AsyncMergeExecutor:
    """Execute merge plans against the PostgreSQL database."""

    REASSIGN_TABLES: tuple[str, ...] = (
        "identifiers", "social_profiles", "addresses",
        "employment_histories", "educations", "breach_records",
        "media_assets", "watchlist_matches", "darkweb_mentions",
        "crypto_wallets", "behavioural_profiles", "credit_risk_assessments",
        "wealth_assessments", "burner_assessments", "relationships",
        "crawl_jobs", "alerts", "criminal_records", "identity_documents",
        "credit_profiles", "identifier_history", "marketing_tags",
        "consumer_segments", "audit_log",
    )

    async def execute(self, plan: dict, session: "AsyncSession") -> dict[str, Any]:
        """
        Execute a merge plan: reassign all child rows to canonical_id, then
        delete the duplicate person row.

        Returns a result dict with merged status and updated table list.
        """
        canonical_id: str = str(plan.get("canonical_id", ""))
        duplicate_id: str = str(plan.get("duplicate_id", ""))

        # Validate UUIDs
        try:
            _uuid_mod.UUID(canonical_id)
            _uuid_mod.UUID(duplicate_id)
        except (ValueError, AttributeError) as exc:
            return {
                "merged": False,
                "error": f"Invalid UUID(s): {exc}",
                "canonical_id": canonical_id,
                "duplicate_id": duplicate_id,
            }

        if canonical_id == duplicate_id:
            return {
                "merged": False,
                "error": "canonical_id and duplicate_id must differ",
                "canonical_id": canonical_id,
                "duplicate_id": duplicate_id,
            }

        tables_updated: list[str] = []

        try:
            for table in self.REASSIGN_TABLES:
                if not _SAFE_TABLE_RE.match(table):
                    logger.warning("AsyncMergeExecutor: skipping unsafe table name %r", table)
                    continue
                stmt = sa_text(
                    f"UPDATE {table} SET person_id = :canonical WHERE person_id = :dup"
                )
                result = await session.execute(
                    stmt,
                    {"canonical": canonical_id, "dup": duplicate_id},
                )
                if result.rowcount > 0:
                    tables_updated.append(table)

            delete_stmt = sa_text("DELETE FROM persons WHERE id = :dup")
            await session.execute(delete_stmt, {"dup": duplicate_id})

            await session.commit()

            return {
                "merged": True,
                "canonical_id": canonical_id,
                "duplicate_id": duplicate_id,
                "tables_updated": tables_updated,
                "merged_at": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as exc:
            await session.rollback()
            logger.exception(
                "AsyncMergeExecutor failed for canonical=%s dup=%s",
                canonical_id,
                duplicate_id,
            )
            return {
                "merged": False,
                "error": str(exc),
                "canonical_id": canonical_id,
                "duplicate_id": duplicate_id,
            }


# ─── score_person_dedup — async enricher entrypoint ──────────────────────────

async def score_person_dedup(
    person_id: str,
    session: "AsyncSession",
) -> list[MergeCandidate]:
    """
    Find merge candidates for a single person by querying their identifiers.

    Steps:
      1. Load the target person and their identifiers from DB.
      2. Build blocking keys (birth year, soundex name, phone prefix).
      3. Fetch candidate persons sharing at least one blocking attribute.
      4. Run FuzzyDeduplicator on the combined set.
      5. Return candidates (excluding self-matches) sorted by score desc.
    """
    try:
        from shared.models.person import Person
        from shared.models.identifier import Identifier
        from shared.models.address import Address
    except ImportError as exc:
        logger.warning("score_person_dedup: shared models not available — %s", exc)
        return []

    try:
        from sqlalchemy import select as sa_select

        # ── Load target person ──────────────────────────────────────────────
        person_stmt = sa_select(Person).where(Person.id == person_id)
        person_result = await session.execute(person_stmt)
        target_person = person_result.scalar_one_or_none()

        if target_person is None:
            logger.warning("score_person_dedup: person %s not found", person_id)
            return []

        # ── Load target identifiers ─────────────────────────────────────────
        ident_stmt = sa_select(Identifier).where(Identifier.person_id == person_id)
        ident_result = await session.execute(ident_stmt)
        target_idents = ident_result.scalars().all()

        phones: list[str] = [
            i.normalized_value or i.value
            for i in target_idents
            if i.type == 'phone' and (i.normalized_value or i.value)
        ]
        emails: list[str] = [
            i.normalized_value or i.value
            for i in target_idents
            if i.type == 'email' and (i.normalized_value or i.value)
        ]
        phone_prefixes: list[str] = [
            re.sub(r'\D', '', p)[:3]
            for p in phones
            if len(re.sub(r'\D', '', p)) >= 3
        ]

        # ── Build blocking query — fetch candidates via blocking keys ────────
        candidate_ids: set[str] = set()

        # Block by birth year
        dob = getattr(target_person, 'dob', None)
        if dob:
            birth_year = str(dob)[:4]
            if birth_year.isdigit():
                by_stmt = sa_select(Person.id).where(
                    sa_text(f"EXTRACT(YEAR FROM dob)::text = :yr")
                ).params(yr=birth_year)
                by_result = await session.execute(by_stmt)
                candidate_ids.update(str(r[0]) for r in by_result.fetchall())

        # Block by soundex of last name
        full_name = getattr(target_person, 'full_name', '') or ''
        if full_name:
            parts = full_name.strip().split()
            last_name = parts[-1] if parts else ''
            if last_name:
                sdx = soundex(last_name)
                # Blocking by last name; soundex key sdx={sdx} used for FuzzyDeduplicator blocking
                ln_stmt = sa_select(Person.id).where(
                    Person.full_name.ilike(f"%{last_name}%")
                ).limit(500)
                ln_result = await session.execute(ln_stmt)
                candidate_ids.update(str(r[0]) for r in ln_result.fetchall())

        # Block by phone prefix via Identifier table
        for prefix in phone_prefixes:
            ph_stmt = (
                sa_select(Identifier.person_id)
                .where(Identifier.type == 'phone')
                .where(
                    sa_text(
                        "regexp_replace(normalized_value, '\\D', '', 'g') LIKE :prefix"
                    ).bindparams(prefix=f"{prefix}%")
                )
            )
            ph_result = await session.execute(ph_stmt)
            candidate_ids.update(str(r[0]) for r in ph_result.fetchall())

        # Remove self
        candidate_ids.discard(str(person_id))

        if not candidate_ids:
            return []

        # ── Load candidate persons + their identifiers ───────────────────────
        cand_stmt = sa_select(Person).where(Person.id.in_(list(candidate_ids)))
        cand_result = await session.execute(cand_stmt)
        candidate_persons = cand_result.scalars().all()

        all_ids = list(candidate_ids) + [str(person_id)]
        cand_ident_stmt = sa_select(Identifier).where(
            Identifier.person_id.in_(all_ids)
        )
        cand_ident_result = await session.execute(cand_ident_stmt)
        all_idents = cand_ident_result.scalars().all()

        # Build a map: person_id → identifier lists
        ident_map: dict[str, dict[str, list[str]]] = {}
        for ident in all_idents:
            pid = str(ident.person_id)
            val = ident.normalized_value or ident.value or ''
            ident_map.setdefault(pid, {'phones': [], 'emails': [], 'other': []})
            if ident.type == 'phone':
                ident_map[pid]['phones'].append(val)
            elif ident.type == 'email':
                ident_map[pid]['emails'].append(val)
            else:
                ident_map[pid]['other'].append(val)

        # ── Load addresses for blocking set ──────────────────────────────────
        addr_stmt = sa_select(Address).where(Address.person_id.in_(all_ids))
        addr_result = await session.execute(addr_stmt)
        all_addresses = addr_result.scalars().all()

        addr_map: dict[str, list[dict]] = {}
        for addr in all_addresses:
            pid = str(addr.person_id)
            addr_map.setdefault(pid, []).append({
                'city': getattr(addr, 'city', ''),
                'state': getattr(addr, 'state', ''),
            })

        def _to_dict(person: Any) -> dict:
            pid = str(person.id)
            im = ident_map.get(pid, {})
            return {
                'id': pid,
                'full_name': getattr(person, 'full_name', '') or '',
                'dob': str(getattr(person, 'dob', '') or ''),
                'phones': im.get('phones', []),
                'emails': im.get('emails', []),
                'identifiers': im.get('other', []),
                'addresses': addr_map.get(pid, []),
            }

        persons_dicts: list[dict] = [
            _to_dict(target_person),
            *(_to_dict(p) for p in candidate_persons),
        ]

        dedup = FuzzyDeduplicator()
        candidates = dedup.find_candidates(persons_dicts)

        # Keep only candidates involving the target person
        target_id_str = str(person_id)
        filtered = [
            c for c in candidates
            if c.id_a == target_id_str or c.id_b == target_id_str
        ]

        return filtered

    except Exception as exc:
        logger.exception("score_person_dedup failed for person_id=%s: %s", person_id, exc)
        return []
