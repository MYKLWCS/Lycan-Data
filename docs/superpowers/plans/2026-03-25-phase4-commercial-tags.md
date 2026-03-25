# Phase 4: Commercial Tags Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the marketing tags engine with 12 new commercial tags across Insurance, Banking, and Wealth categories plus refined Lending tags, wire them into a `PersonSignals` assembler, build a `CommercialTaggerDaemon` that runs every 15 minutes on newly enriched persons, and expose four API endpoints for triggering and querying commercial tags.

**Architecture:** All new tag taxonomy (`InsuranceTag`, `BankingTag`, `WealthTag`) and scorer functions live in `modules/enrichers/marketing_tags.py` alongside the existing engine — no new taxonomy files. `PersonSignals` assembly and `CommercialTaggerDaemon` live in a new `modules/enrichers/commercial_tagger.py`. The daemon queries `Person.last_scraped_at > last_run_at` (tracked in an in-memory timestamp), runs `CommercialTagsEngine.tag_person()` for each result, and upserts `MarketingTag` rows with a `tag_category` field set to the enum class name. Two new API routes (`GET /tags/summary`, `POST /tags/batch`) extend the existing `api/routes/marketing.py` router.

**Tech Stack:** Python asyncio, SQLAlchemy async, PostgreSQL, FastAPI

**Codebase ground truth (read before implementing):**
- `WealthAssessment` columns: `income_estimate_usd`, `net_worth_estimate_usd`, `vehicle_signal`, `property_signal`, `wealth_band`
- `EmploymentHistory`: `is_current: bool` (not a status string)
- `LendingTag` already has: `AUTO_LOAN_CANDIDATE`, `PAYDAY_LOAN_CANDIDATE`, `PERSONAL_LOAN_CANDIDATE`, `REFINANCE_CANDIDATE`, `DEBT_CONSOLIDATION`. Uses `MORTGAGE_READY` (not `MORTGAGE_CANDIDATE`) — rename it to `MORTGAGE_CANDIDATE = "mortgage"` per spec.
- `Person` inherits `DataQualityMixin` which provides `last_scraped_at: datetime | None`
- Existing API routes already implement `POST /persons/{id}/tag` and `GET /persons/{id}/tags` — do not duplicate them; only add `GET /tags/summary` and `POST /tags/batch`
- `MarketingTag.tag_category` column exists — populate it with the StrEnum class name (`"InsuranceTag"`, `"BankingTag"`, `"WealthTag"`, `"LendingTag"`)
- Run tests: `python3 -m pytest tests/ -v`
- Run targeted tests: `python3 -m pytest tests/test_enrichers/test_commercial_tags.py -v`

---

## Task 1: Add New Tag StrEnums to `marketing_tags.py`

**Files:**
- Modify: `modules/enrichers/marketing_tags.py`

**What:** Add three new `StrEnum` classes (`InsuranceTag`, `BankingTag`, `WealthTag`) and rename `LendingTag.MORTGAGE_READY` to `MORTGAGE_CANDIDATE` with value `"mortgage"`. All new enum members per spec.

- [ ] **Write failing test** — `tests/test_enrichers/test_commercial_tags.py` (create this file):

```python
"""Phase 4 commercial tags — pure logic tests, no DB required."""

import pytest

from modules.enrichers.marketing_tags import (
    BankingTag,
    InsuranceTag,
    LendingTag,
    WealthTag,
)


def test_insurance_tag_values_exist():
    assert InsuranceTag.INSURANCE_AUTO == "insurance_auto"
    assert InsuranceTag.INSURANCE_LIFE == "insurance_life"
    assert InsuranceTag.INSURANCE_HEALTH == "insurance_health"


def test_banking_tag_values_exist():
    assert BankingTag.BANKING_BASIC == "banking_basic"
    assert BankingTag.BANKING_PREMIUM == "banking_premium"


def test_wealth_tag_values_exist():
    assert WealthTag.HIGH_NET_WORTH == "high_net_worth"


def test_lending_tag_mortgage_candidate_renamed():
    assert LendingTag.MORTGAGE_CANDIDATE == "mortgage"


def test_lending_tag_auto_loan_exists():
    assert LendingTag.AUTO_LOAN_CANDIDATE == "auto_loan_candidate"


def test_lending_tag_debt_consolidation_exists():
    assert LendingTag.DEBT_CONSOLIDATION == "debt_consolidation"
```

- [ ] **Run → Expected FAIL:**

```
python3 -m pytest tests/test_enrichers/test_commercial_tags.py::test_insurance_tag_values_exist -v
# ImportError: cannot import name 'InsuranceTag' from 'modules.enrichers.marketing_tags'
```

- [ ] **Implement** — in `modules/enrichers/marketing_tags.py`, after the `LifeStageTag` class block:

  1. Rename `MORTGAGE_READY = "mortgage_ready"` → `MORTGAGE_CANDIDATE = "mortgage"` inside `LendingTag`.
  2. Append new StrEnum classes:

```python
class InsuranceTag(StrEnum):
    INSURANCE_AUTO = "insurance_auto"
    INSURANCE_LIFE = "insurance_life"
    INSURANCE_HEALTH = "insurance_health"


class BankingTag(StrEnum):
    BANKING_BASIC = "banking_basic"
    BANKING_PREMIUM = "banking_premium"


class WealthTag(StrEnum):
    HIGH_NET_WORTH = "high_net_worth"
```

- [ ] **Run → Expected PASS:**

```
python3 -m pytest tests/test_enrichers/test_commercial_tags.py -v -k "tag_values or renamed"
# 6 passed
```

- [ ] **Commit:**

```bash
git add modules/enrichers/marketing_tags.py tests/test_enrichers/test_commercial_tags.py
git commit -m "feat(phase4): add InsuranceTag, BankingTag, WealthTag StrEnums; rename MORTGAGE_READY → MORTGAGE_CANDIDATE"
```

---

## Task 2: Extend `_THRESHOLDS` with New Tag Entries

**Files:**
- Modify: `modules/enrichers/marketing_tags.py`

**What:** Add all 12 new tag threshold entries to the `_THRESHOLDS` dict. Import the new enums at the point of dict construction (they're in the same file).

- [ ] **Write failing test** — append to `tests/test_enrichers/test_commercial_tags.py`:

```python
from modules.enrichers.marketing_tags import _THRESHOLDS


def test_thresholds_insurance_auto():
    assert _THRESHOLDS[InsuranceTag.INSURANCE_AUTO] == pytest.approx(0.60)


def test_thresholds_insurance_life():
    assert _THRESHOLDS[InsuranceTag.INSURANCE_LIFE] == pytest.approx(0.65)


def test_thresholds_insurance_health():
    assert _THRESHOLDS[InsuranceTag.INSURANCE_HEALTH] == pytest.approx(0.65)


def test_thresholds_banking_basic():
    assert _THRESHOLDS[BankingTag.BANKING_BASIC] == pytest.approx(0.60)


def test_thresholds_banking_premium():
    assert _THRESHOLDS[BankingTag.BANKING_PREMIUM] == pytest.approx(0.70)


def test_thresholds_high_net_worth():
    assert _THRESHOLDS[WealthTag.HIGH_NET_WORTH] == pytest.approx(0.70)


def test_thresholds_auto_loan_candidate():
    assert _THRESHOLDS[LendingTag.AUTO_LOAN_CANDIDATE] == pytest.approx(0.65)


def test_thresholds_payday_loan_candidate():
    assert _THRESHOLDS[LendingTag.PAYDAY_LOAN_CANDIDATE] == pytest.approx(0.65)


def test_thresholds_personal_loan_candidate():
    assert _THRESHOLDS[LendingTag.PERSONAL_LOAN_CANDIDATE] == pytest.approx(0.60)


def test_thresholds_mortgage_candidate():
    assert _THRESHOLDS[LendingTag.MORTGAGE_CANDIDATE] == pytest.approx(0.70)


def test_thresholds_refinance_candidate():
    assert _THRESHOLDS[LendingTag.REFINANCE_CANDIDATE] == pytest.approx(0.65)


def test_thresholds_debt_consolidation():
    assert _THRESHOLDS[LendingTag.DEBT_CONSOLIDATION] == pytest.approx(0.65)
```

- [ ] **Run → Expected FAIL:**

```
python3 -m pytest tests/test_enrichers/test_commercial_tags.py -v -k "thresholds"
# KeyError: <InsuranceTag.INSURANCE_AUTO: 'insurance_auto'>  (or similar)
```

- [ ] **Implement** — extend `_THRESHOLDS` in `modules/enrichers/marketing_tags.py`:

```python
_THRESHOLDS: dict[str, float] = {
    # --- existing entries ---
    LendingTag.TITLE_LOAN_CANDIDATE: 0.70,
    InvestmentTag.CRYPTO_INVESTOR: 0.70,
    InvestmentTag.REAL_ESTATE_INVESTOR: 0.70,
    LifeStageTag.RECENT_MOVER: 0.70,
    LifeStageTag.NEW_PARENT: 0.70,
    BehaviouralTag.ACTIVE_GAMBLER: 0.65,
    BehaviouralTag.LUXURY_BUYER: 0.65,
    LifeStageTag.RETIRING_SOON: 0.65,
    # --- phase 4 additions ---
    InsuranceTag.INSURANCE_AUTO: 0.60,
    InsuranceTag.INSURANCE_LIFE: 0.65,
    InsuranceTag.INSURANCE_HEALTH: 0.65,
    BankingTag.BANKING_BASIC: 0.60,
    BankingTag.BANKING_PREMIUM: 0.70,
    WealthTag.HIGH_NET_WORTH: 0.70,
    LendingTag.AUTO_LOAN_CANDIDATE: 0.65,
    LendingTag.PAYDAY_LOAN_CANDIDATE: 0.65,
    LendingTag.PERSONAL_LOAN_CANDIDATE: 0.60,
    LendingTag.MORTGAGE_CANDIDATE: 0.70,
    LendingTag.REFINANCE_CANDIDATE: 0.65,
    LendingTag.DEBT_CONSOLIDATION: 0.65,
}
```

- [ ] **Run → Expected PASS:**

```
python3 -m pytest tests/test_enrichers/test_commercial_tags.py -v -k "thresholds"
# 12 passed
```

- [ ] **Commit:**

```bash
git add modules/enrichers/marketing_tags.py
git commit -m "feat(phase4): extend _THRESHOLDS with 12 commercial tag entries"
```

---

## Task 3: Add Scorer Functions for Insurance Tags

**Files:**
- Modify: `modules/enrichers/marketing_tags.py`

**What:** Add three scorer functions for `InsuranceTag`: `_score_insurance_auto`, `_score_insurance_life`, `_score_insurance_health`. Each takes a `PersonSignals`-compatible set of primitive arguments (no DB — pure computation). The functions follow the existing `(inputs) -> tuple[float, list[str]]` pattern.

- [ ] **Write failing test** — append to `tests/test_enrichers/test_commercial_tags.py`:

```python
from modules.enrichers.marketing_tags import (
    _score_insurance_auto,
    _score_insurance_health,
    _score_insurance_life,
)


# ── _score_insurance_auto ────────────────────────────────────────────────────


def test_insurance_auto_vehicle_present():
    score, reasons = _score_insurance_auto(has_vehicle=True)
    assert score >= 0.80
    assert any("vehicle" in r.lower() for r in reasons)


def test_insurance_auto_no_vehicle():
    score, reasons = _score_insurance_auto(has_vehicle=False)
    assert score == 0.0
    assert reasons == []


# ── _score_insurance_life ────────────────────────────────────────────────────


def test_insurance_life_age_and_income():
    score, reasons = _score_insurance_life(age=35, income_estimate=60_000.0)
    assert score >= 0.65
    assert any("age" in r.lower() for r in reasons)


def test_insurance_life_age_out_of_range():
    score, _ = _score_insurance_life(age=17, income_estimate=60_000.0)
    assert score < 0.65


def test_insurance_life_no_age():
    score, _ = _score_insurance_life(age=None, income_estimate=None)
    assert score < 0.65


# ── _score_insurance_health ──────────────────────────────────────────────────


def test_insurance_health_employed_adult():
    score, reasons = _score_insurance_health(age=30, is_employed=True)
    assert score >= 0.65
    assert any("employ" in r.lower() for r in reasons)


def test_insurance_health_unemployed():
    score, reasons = _score_insurance_health(age=30, is_employed=False)
    assert score < 0.65


def test_insurance_health_age_out_of_range():
    score, _ = _score_insurance_health(age=17, is_employed=True)
    assert score < 0.65
```

- [ ] **Run → Expected FAIL:**

```
python3 -m pytest tests/test_enrichers/test_commercial_tags.py -v -k "insurance"
# ImportError: cannot import name '_score_insurance_auto' ...
```

- [ ] **Implement** — add to `modules/enrichers/marketing_tags.py` (after existing scorers, before `HighInterestBorrowerScorer`):

```python
def _score_insurance_auto(has_vehicle: bool) -> tuple[float, list[str]]:
    if not has_vehicle:
        return 0.0, []
    return 0.90, ["vehicle record present — auto insurance candidate"]


def _score_insurance_life(
    age: int | None,
    income_estimate: float | None,
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    if age is not None and 25 <= age <= 65:
        score += 0.50
        reasons.append(f"age {age} in life insurance target range (25-65)")

    if income_estimate is not None and income_estimate >= 30_000:
        score += 0.30
        reasons.append(f"income signal: ${income_estimate:,.0f}")

    return _clamp(score), reasons


def _score_insurance_health(
    age: int | None,
    is_employed: bool,
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    if age is not None and 18 <= age <= 65:
        score += 0.40
        reasons.append(f"age {age} in health insurance target range (18-65)")

    if is_employed:
        score += 0.35
        reasons.append("currently employed — health insurance candidate")

    return _clamp(score), reasons
```

- [ ] **Run → Expected PASS:**

```
python3 -m pytest tests/test_enrichers/test_commercial_tags.py -v -k "insurance"
# 8 passed
```

- [ ] **Commit:**

```bash
git add modules/enrichers/marketing_tags.py
git commit -m "feat(phase4): add _score_insurance_auto/life/health scorer functions"
```

---

## Task 4: Add Scorer Functions for Banking and Wealth Tags

**Files:**
- Modify: `modules/enrichers/marketing_tags.py`

**What:** Add `_score_banking_basic`, `_score_banking_premium`, and `_score_high_net_worth` scorer functions.

- [ ] **Write failing test** — append to `tests/test_enrichers/test_commercial_tags.py`:

```python
from modules.enrichers.marketing_tags import (
    _score_banking_basic,
    _score_banking_premium,
    _score_high_net_worth,
)


# ── _score_banking_basic ─────────────────────────────────────────────────────


def test_banking_basic_employed_adult():
    score, reasons = _score_banking_basic(is_employed=True, age=25)
    assert score >= 0.60
    assert any("employ" in r.lower() for r in reasons)


def test_banking_basic_unemployed():
    score, _ = _score_banking_basic(is_employed=False, age=25)
    assert score < 0.60


def test_banking_basic_minor():
    score, _ = _score_banking_basic(is_employed=False, age=17)
    assert score < 0.60


# ── _score_banking_premium ───────────────────────────────────────────────────


def test_banking_premium_high_income_and_investment():
    score, reasons = _score_banking_premium(
        income_estimate=150_000.0,
        net_worth_estimate=500_000.0,
        has_investment_signals=True,
    )
    assert score >= 0.70
    assert any("income" in r.lower() for r in reasons)


def test_banking_premium_low_income():
    score, _ = _score_banking_premium(
        income_estimate=25_000.0,
        net_worth_estimate=None,
        has_investment_signals=False,
    )
    assert score < 0.70


def test_banking_premium_no_income():
    score, _ = _score_banking_premium(
        income_estimate=None,
        net_worth_estimate=None,
        has_investment_signals=False,
    )
    assert score == 0.0


# ── _score_high_net_worth ────────────────────────────────────────────────────


def test_high_net_worth_all_signals():
    score, reasons = _score_high_net_worth(
        net_worth_estimate=2_000_000.0,
        has_property=True,
        has_investment_signals=True,
    )
    assert score >= 0.70
    assert any("net worth" in r.lower() for r in reasons)


def test_high_net_worth_no_data():
    score, _ = _score_high_net_worth(
        net_worth_estimate=None,
        has_property=False,
        has_investment_signals=False,
    )
    assert score == 0.0


def test_high_net_worth_below_threshold():
    score, _ = _score_high_net_worth(
        net_worth_estimate=50_000.0,
        has_property=False,
        has_investment_signals=False,
    )
    assert score < 0.70
```

- [ ] **Run → Expected FAIL:**

```
python3 -m pytest tests/test_enrichers/test_commercial_tags.py -v -k "banking or net_worth"
# ImportError: cannot import name '_score_banking_basic' ...
```

- [ ] **Implement** — add to `modules/enrichers/marketing_tags.py`:

```python
def _score_banking_basic(
    is_employed: bool,
    age: int | None,
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    if age is not None and age >= 18:
        score += 0.30
        reasons.append(f"adult: age {age}")

    if is_employed:
        score += 0.40
        reasons.append("currently employed — basic banking candidate")

    return _clamp(score), reasons


def _score_banking_premium(
    income_estimate: float | None,
    net_worth_estimate: float | None,
    has_investment_signals: bool,
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    if income_estimate is None:
        return 0.0, []

    if income_estimate >= 100_000:
        score += 0.40
        reasons.append(f"high income signal: ${income_estimate:,.0f}")
    elif income_estimate >= 60_000:
        score += 0.20
        reasons.append(f"upper-middle income signal: ${income_estimate:,.0f}")

    if net_worth_estimate is not None and net_worth_estimate >= 250_000:
        score += 0.20
        reasons.append(f"net worth signal: ${net_worth_estimate:,.0f}")

    if has_investment_signals:
        score += 0.20
        reasons.append("investment activity signals present")

    return _clamp(score), reasons


def _score_high_net_worth(
    net_worth_estimate: float | None,
    has_property: bool,
    has_investment_signals: bool,
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    if net_worth_estimate is None:
        return 0.0, []

    if net_worth_estimate >= 1_000_000:
        score += 0.50
        reasons.append(f"net worth >= $1M: ${net_worth_estimate:,.0f}")
    elif net_worth_estimate >= 500_000:
        score += 0.30
        reasons.append(f"net worth >= $500K: ${net_worth_estimate:,.0f}")
    else:
        return 0.0, []

    if has_property:
        score += 0.30
        reasons.append("property record present")

    if has_investment_signals:
        score += 0.20
        reasons.append("investment activity signals present")

    return _clamp(score), reasons
```

- [ ] **Run → Expected PASS:**

```
python3 -m pytest tests/test_enrichers/test_commercial_tags.py -v -k "banking or net_worth"
# 9 passed
```

- [ ] **Commit:**

```bash
git add modules/enrichers/marketing_tags.py
git commit -m "feat(phase4): add _score_banking_basic/premium and _score_high_net_worth scorer functions"
```

---

## Task 5: Add Scorer Functions for New Lending Tags

**Files:**
- Modify: `modules/enrichers/marketing_tags.py`

**What:** Add `_score_auto_loan_candidate`, `_score_payday_loan_candidate`, `_score_personal_loan_candidate`, `_score_mortgage_candidate`, `_score_refinance_candidate`, `_score_debt_consolidation`. These replace/supplement the signals that the existing `_score_title_loan` already handles — they are distinct functions targeting the six new/renamed `LendingTag` values.

Note: `PAYDAY_LOAN_CANDIDATE` and `REFINANCE_CANDIDATE` already existed in `LendingTag` before Phase 4 but had no dedicated scorers. `AUTO_LOAN_CANDIDATE`, `PERSONAL_LOAN_CANDIDATE`, `DEBT_CONSOLIDATION` also existed. This task wires them all up to explicit scorer functions driven by `PersonSignals` fields.

- [ ] **Write failing test** — append to `tests/test_enrichers/test_commercial_tags.py`:

```python
from modules.enrichers.marketing_tags import (
    _score_auto_loan_candidate,
    _score_debt_consolidation,
    _score_mortgage_candidate,
    _score_payday_loan_candidate,
    _score_personal_loan_candidate,
    _score_refinance_candidate,
)


# ── _score_auto_loan_candidate ───────────────────────────────────────────────


def test_auto_loan_vehicle_no_property_medium_income():
    score, reasons = _score_auto_loan_candidate(
        has_vehicle=True, has_property=False, income_estimate=45_000.0
    )
    assert score >= 0.65
    assert any("vehicle" in r.lower() for r in reasons)


def test_auto_loan_no_vehicle():
    score, _ = _score_auto_loan_candidate(
        has_vehicle=False, has_property=True, income_estimate=45_000.0
    )
    assert score < 0.65


# ── _score_payday_loan_candidate ─────────────────────────────────────────────


def test_payday_loan_high_distress_low_income():
    score, reasons = _score_payday_loan_candidate(
        financial_distress_score=0.7, has_property=False, income_estimate=20_000.0
    )
    assert score >= 0.65
    assert any("distress" in r.lower() for r in reasons)


def test_payday_loan_low_distress():
    score, _ = _score_payday_loan_candidate(
        financial_distress_score=0.2, has_property=False, income_estimate=20_000.0
    )
    assert score < 0.65


# ── _score_personal_loan_candidate ───────────────────────────────────────────


def test_personal_loan_employed():
    score, reasons = _score_personal_loan_candidate(is_employed=True, financial_distress_score=0.3)
    assert score >= 0.60
    assert any("employ" in r.lower() for r in reasons)


def test_personal_loan_unemployed_no_distress():
    score, _ = _score_personal_loan_candidate(is_employed=False, financial_distress_score=0.1)
    assert score < 0.60


# ── _score_mortgage_candidate ────────────────────────────────────────────────


def test_mortgage_candidate_property_record():
    score, reasons = _score_mortgage_candidate(
        has_property=True, income_estimate=80_000.0
    )
    assert score >= 0.70
    assert any("property" in r.lower() for r in reasons)


def test_mortgage_candidate_high_income_no_property():
    score, reasons = _score_mortgage_candidate(
        has_property=False, income_estimate=120_000.0
    )
    assert score >= 0.70
    assert any("income" in r.lower() for r in reasons)


def test_mortgage_candidate_no_signals():
    score, _ = _score_mortgage_candidate(has_property=False, income_estimate=15_000.0)
    assert score < 0.70


# ── _score_refinance_candidate ───────────────────────────────────────────────


def test_refinance_candidate_property_and_distress():
    score, reasons = _score_refinance_candidate(
        has_property=True, financial_distress_score=0.6
    )
    assert score >= 0.65
    assert any("distress" in r.lower() for r in reasons)


def test_refinance_candidate_no_property():
    score, _ = _score_refinance_candidate(has_property=False, financial_distress_score=0.8)
    assert score < 0.65


# ── _score_debt_consolidation ────────────────────────────────────────────────


def test_debt_consolidation_multiple_signals_and_distress():
    score, reasons = _score_debt_consolidation(
        financial_distress_score=0.7, criminal_count=1, has_vehicle=True, has_property=False
    )
    assert score >= 0.65
    assert any("distress" in r.lower() for r in reasons)


def test_debt_consolidation_no_distress():
    score, _ = _score_debt_consolidation(
        financial_distress_score=0.1, criminal_count=0, has_vehicle=False, has_property=False
    )
    assert score < 0.65
```

- [ ] **Run → Expected FAIL:**

```
python3 -m pytest tests/test_enrichers/test_commercial_tags.py -v -k "auto_loan or payday or personal_loan or mortgage or refinance or debt_consol"
# ImportError: cannot import name '_score_auto_loan_candidate' ...
```

- [ ] **Implement** — add to `modules/enrichers/marketing_tags.py`:

```python
def _score_auto_loan_candidate(
    has_vehicle: bool,
    has_property: bool,
    income_estimate: float | None,
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    if not has_vehicle:
        return 0.0, []

    score += 0.40
    reasons.append("vehicle record present")

    if not has_property:
        score += 0.20
        reasons.append("no property record — likely renter needing auto financing")

    if income_estimate is not None and 25_000 <= income_estimate <= 80_000:
        score += 0.20
        reasons.append(f"medium income signal: ${income_estimate:,.0f}")
    elif income_estimate is not None and income_estimate > 0:
        score += 0.10
        reasons.append(f"income signal present: ${income_estimate:,.0f}")

    return _clamp(score), reasons


def _score_payday_loan_candidate(
    financial_distress_score: float,
    has_property: bool,
    income_estimate: float | None,
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    if financial_distress_score <= 0.5:
        return 0.0, []

    score += 0.40
    reasons.append(f"financial distress score: {financial_distress_score:.2f}")

    if not has_property:
        score += 0.20
        reasons.append("no property collateral")

    if income_estimate is not None and income_estimate < 35_000:
        score += 0.20
        reasons.append(f"low income signal: ${income_estimate:,.0f}")
    elif income_estimate is None:
        score += 0.10
        reasons.append("no income data — elevated risk signal")

    return _clamp(score), reasons


def _score_personal_loan_candidate(
    is_employed: bool,
    financial_distress_score: float,
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    if is_employed:
        score += 0.45
        reasons.append("currently employed — personal loan repayment capacity")

    if financial_distress_score > 0.3:
        score += 0.25
        reasons.append(f"financial distress signal: {financial_distress_score:.2f}")

    return _clamp(score), reasons


def _score_mortgage_candidate(
    has_property: bool,
    income_estimate: float | None,
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    if has_property:
        score += 0.50
        reasons.append("property record present — homeowner/mortgage signal")

    if income_estimate is not None and income_estimate >= 80_000:
        score += 0.40
        reasons.append(f"high income signal: ${income_estimate:,.0f}")
    elif income_estimate is not None and income_estimate >= 50_000:
        score += 0.20
        reasons.append(f"moderate income signal: ${income_estimate:,.0f}")

    return _clamp(score), reasons


def _score_refinance_candidate(
    has_property: bool,
    financial_distress_score: float,
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    if not has_property:
        return 0.0, []

    score += 0.40
    reasons.append("property record — existing mortgage signal")

    if financial_distress_score > 0.4:
        score += 0.35
        reasons.append(f"financial distress signal: {financial_distress_score:.2f} — refinance motivation")

    return _clamp(score), reasons


def _score_debt_consolidation(
    financial_distress_score: float,
    criminal_count: int,
    has_vehicle: bool,
    has_property: bool,
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    if financial_distress_score <= 0.4:
        return 0.0, []

    score += 0.35
    reasons.append(f"financial distress score: {financial_distress_score:.2f}")

    loan_signal_count = sum([has_vehicle, has_property, criminal_count > 0])
    if loan_signal_count >= 2:
        score += 0.30
        reasons.append(f"multiple loan exposure signals: {loan_signal_count}")
    elif loan_signal_count == 1:
        score += 0.15
        reasons.append("single loan exposure signal present")

    return _clamp(score), reasons
```

- [ ] **Run → Expected PASS:**

```
python3 -m pytest tests/test_enrichers/test_commercial_tags.py -v -k "auto_loan or payday or personal_loan or mortgage or refinance or debt_consol"
# 12 passed
```

- [ ] **Commit:**

```bash
git add modules/enrichers/marketing_tags.py
git commit -m "feat(phase4): add 6 lending scorer functions (auto, payday, personal, mortgage, refinance, debt_consolidation)"
```

---

## Task 6: `PersonSignals` Dataclass + Assembler

**Files:**
- Create: `modules/enrichers/commercial_tagger.py`

**What:** Create `PersonSignals` dataclass and `assemble_person_signals(person_id, session)` async function that gathers all fields from the DB in a single sequential pass. `has_investment_signals` is a boolean derived from `WealthAssessment.crypto_signal > 0.3 or WealthAssessment.luxury_signal > 0.3`.

- [ ] **Write failing test** — append to `tests/test_enrichers/test_commercial_tags.py`:

```python
from modules.enrichers.commercial_tagger import PersonSignals


def test_person_signals_is_dataclass():
    import dataclasses
    assert dataclasses.is_dataclass(PersonSignals)


def test_person_signals_fields():
    import uuid
    s = PersonSignals(
        person_id=uuid.uuid4(),
        has_vehicle=True,
        has_property=False,
        financial_distress_score=0.4,
        gambling_score=0.1,
        income_estimate=55_000.0,
        net_worth_estimate=None,
        is_employed=True,
        age=34,
        criminal_count=0,
        has_investment_signals=False,
    )
    assert s.has_vehicle is True
    assert s.age == 34
    assert s.income_estimate == 55_000.0
```

- [ ] **Run → Expected FAIL:**

```
python3 -m pytest tests/test_enrichers/test_commercial_tags.py -v -k "person_signals"
# ModuleNotFoundError: No module named 'modules.enrichers.commercial_tagger'
```

- [ ] **Implement** — create `modules/enrichers/commercial_tagger.py`:

```python
"""Commercial Tagger — PersonSignals assembly and CommercialTaggerDaemon."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.enrichers.marketing_tags import (
    BankingTag,
    InsuranceTag,
    LendingTag,
    MarketingTagsEngine,
    TagResult,
    WealthTag,
    _THRESHOLDS,
    _clamp,
    _compute_age,
    _score_auto_loan_candidate,
    _score_banking_basic,
    _score_banking_premium,
    _score_debt_consolidation,
    _score_high_net_worth,
    _score_insurance_auto,
    _score_insurance_health,
    _score_insurance_life,
    _score_mortgage_candidate,
    _score_payday_loan_candidate,
    _score_personal_loan_candidate,
    _score_refinance_candidate,
)
from shared.db import async_session_factory
from shared.events import event_bus
from shared.models.behavioural import BehaviouralProfile
from shared.models.criminal import CriminalRecord
from shared.models.employment import EmploymentHistory
from shared.models.marketing import MarketingTag
from shared.models.person import Person
from shared.models.wealth import WealthAssessment

logger = logging.getLogger(__name__)


# ─── PersonSignals ─────────────────────────────────────────────────────────────


@dataclass
class PersonSignals:
    person_id: UUID
    has_vehicle: bool
    has_property: bool
    financial_distress_score: float
    gambling_score: float
    income_estimate: float | None
    net_worth_estimate: float | None
    is_employed: bool
    age: int | None
    criminal_count: int
    has_investment_signals: bool


async def assemble_person_signals(person_id: UUID, session: AsyncSession) -> PersonSignals:
    """Build a PersonSignals from DB in sequential queries (single session)."""

    person = (
        (await session.execute(select(Person).where(Person.id == person_id)))
        .scalars()
        .first()
    )

    # Employment — is_current rows
    employment = list(
        (
            await session.execute(
                select(EmploymentHistory).where(
                    EmploymentHistory.person_id == person_id,
                    EmploymentHistory.is_current == True,  # noqa: E712
                )
            )
        )
        .scalars()
        .all()
    )

    # Criminal records count
    criminal_count_row = (
        await session.execute(
            select(func.count(CriminalRecord.id)).where(CriminalRecord.person_id == person_id)
        )
    ).scalar()

    # Latest wealth assessment
    wealth = (
        (
            await session.execute(
                select(WealthAssessment)
                .where(WealthAssessment.person_id == person_id)
                .order_by(WealthAssessment.assessed_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )

    # Behavioural profile
    behavioural = (
        (
            await session.execute(
                select(BehaviouralProfile).where(BehaviouralProfile.person_id == person_id)
            )
        )
        .scalars()
        .first()
    )

    # Derived
    dob = person.date_of_birth if person else None
    age = _compute_age(dob)
    is_employed = len(employment) > 0
    financial_distress_score = behavioural.financial_distress_score if behavioural else 0.0
    gambling_score = behavioural.gambling_score if behavioural else 0.0
    income_estimate = wealth.income_estimate_usd if wealth else None
    net_worth_estimate = wealth.net_worth_estimate_usd if wealth else None
    has_vehicle = bool(wealth and wealth.vehicle_signal > 0.3)
    has_property = bool(wealth and wealth.property_signal > 0.3)
    has_investment_signals = bool(
        wealth and (wealth.crypto_signal > 0.3 or wealth.luxury_signal > 0.3)
    )

    return PersonSignals(
        person_id=person_id,
        has_vehicle=has_vehicle,
        has_property=has_property,
        financial_distress_score=financial_distress_score,
        gambling_score=gambling_score,
        income_estimate=income_estimate,
        net_worth_estimate=net_worth_estimate,
        is_employed=is_employed,
        age=age,
        criminal_count=int(criminal_count_row or 0),
        has_investment_signals=has_investment_signals,
    )
```

- [ ] **Run → Expected PASS:**

```
python3 -m pytest tests/test_enrichers/test_commercial_tags.py -v -k "person_signals"
# 2 passed
```

- [ ] **Commit:**

```bash
git add modules/enrichers/commercial_tagger.py
git commit -m "feat(phase4): add PersonSignals dataclass and assemble_person_signals() async assembler"
```

---

## Task 7: `CommercialTagsEngine` — Tags from `PersonSignals`

**Files:**
- Modify: `modules/enrichers/commercial_tagger.py`

**What:** Add `CommercialTagsEngine` class with a `tag_person(signals: PersonSignals) -> list[TagResult]` method that runs all 12 new scorers against a fully populated `PersonSignals` and returns results above threshold. This engine is pure computation — no DB calls. The `MarketingTagsEngine` handles DB reads; this engine handles the commercial scoring layer.

- [ ] **Write failing test** — append to `tests/test_enrichers/test_commercial_tags.py`:

```python
import uuid
from modules.enrichers.commercial_tagger import CommercialTagsEngine, PersonSignals
from modules.enrichers.marketing_tags import InsuranceTag, BankingTag, WealthTag, LendingTag


def _make_signals(**overrides) -> PersonSignals:
    defaults = dict(
        person_id=uuid.uuid4(),
        has_vehicle=False,
        has_property=False,
        financial_distress_score=0.0,
        gambling_score=0.0,
        income_estimate=None,
        net_worth_estimate=None,
        is_employed=False,
        age=None,
        criminal_count=0,
        has_investment_signals=False,
    )
    defaults.update(overrides)
    return PersonSignals(**defaults)


def test_commercial_engine_insurance_auto_tag():
    engine = CommercialTagsEngine()
    signals = _make_signals(has_vehicle=True)
    results = engine.tag_person(signals)
    tags = [r.tag for r in results]
    assert InsuranceTag.INSURANCE_AUTO in tags


def test_commercial_engine_banking_basic_tag():
    engine = CommercialTagsEngine()
    signals = _make_signals(is_employed=True, age=30)
    results = engine.tag_person(signals)
    tags = [r.tag for r in results]
    assert BankingTag.BANKING_BASIC in tags


def test_commercial_engine_high_net_worth_tag():
    engine = CommercialTagsEngine()
    signals = _make_signals(
        net_worth_estimate=1_500_000.0,
        has_property=True,
        has_investment_signals=True,
    )
    results = engine.tag_person(signals)
    tags = [r.tag for r in results]
    assert WealthTag.HIGH_NET_WORTH in tags


def test_commercial_engine_returns_tag_results_with_reasoning():
    engine = CommercialTagsEngine()
    signals = _make_signals(has_vehicle=True)
    results = engine.tag_person(signals)
    for r in results:
        assert isinstance(r.reasoning, list)
        assert len(r.reasoning) > 0
        assert 0.0 <= r.confidence <= 1.0


def test_commercial_engine_no_signals_returns_empty():
    engine = CommercialTagsEngine()
    signals = _make_signals()  # all defaults — nothing fires
    results = engine.tag_person(signals)
    assert results == []
```

- [ ] **Run → Expected FAIL:**

```
python3 -m pytest tests/test_enrichers/test_commercial_tags.py -v -k "commercial_engine"
# ImportError: cannot import name 'CommercialTagsEngine' ...
```

- [ ] **Implement** — append to `modules/enrichers/commercial_tagger.py`:

```python
# ─── CommercialTagsEngine ──────────────────────────────────────────────────────


_COMMERCIAL_TAG_CATEGORY: dict[str, str] = {
    InsuranceTag.INSURANCE_AUTO: "InsuranceTag",
    InsuranceTag.INSURANCE_LIFE: "InsuranceTag",
    InsuranceTag.INSURANCE_HEALTH: "InsuranceTag",
    BankingTag.BANKING_BASIC: "BankingTag",
    BankingTag.BANKING_PREMIUM: "BankingTag",
    WealthTag.HIGH_NET_WORTH: "WealthTag",
    LendingTag.AUTO_LOAN_CANDIDATE: "LendingTag",
    LendingTag.PAYDAY_LOAN_CANDIDATE: "LendingTag",
    LendingTag.PERSONAL_LOAN_CANDIDATE: "LendingTag",
    LendingTag.MORTGAGE_CANDIDATE: "LendingTag",
    LendingTag.REFINANCE_CANDIDATE: "LendingTag",
    LendingTag.DEBT_CONSOLIDATION: "LendingTag",
}


class CommercialTagsEngine:
    """Run all Phase 4 commercial scorers against a PersonSignals struct."""

    def tag_person(self, signals: PersonSignals) -> list[TagResult]:
        now = datetime.now(UTC)
        scoring_map: list[tuple[str, float, list[str]]] = []

        # Insurance
        s, r = _score_insurance_auto(signals.has_vehicle)
        scoring_map.append((InsuranceTag.INSURANCE_AUTO, s, r))

        s, r = _score_insurance_life(signals.age, signals.income_estimate)
        scoring_map.append((InsuranceTag.INSURANCE_LIFE, s, r))

        s, r = _score_insurance_health(signals.age, signals.is_employed)
        scoring_map.append((InsuranceTag.INSURANCE_HEALTH, s, r))

        # Banking
        s, r = _score_banking_basic(signals.is_employed, signals.age)
        scoring_map.append((BankingTag.BANKING_BASIC, s, r))

        s, r = _score_banking_premium(
            signals.income_estimate,
            signals.net_worth_estimate,
            signals.has_investment_signals,
        )
        scoring_map.append((BankingTag.BANKING_PREMIUM, s, r))

        # Wealth
        s, r = _score_high_net_worth(
            signals.net_worth_estimate,
            signals.has_property,
            signals.has_investment_signals,
        )
        scoring_map.append((WealthTag.HIGH_NET_WORTH, s, r))

        # Lending
        s, r = _score_auto_loan_candidate(
            signals.has_vehicle, signals.has_property, signals.income_estimate
        )
        scoring_map.append((LendingTag.AUTO_LOAN_CANDIDATE, s, r))

        s, r = _score_payday_loan_candidate(
            signals.financial_distress_score, signals.has_property, signals.income_estimate
        )
        scoring_map.append((LendingTag.PAYDAY_LOAN_CANDIDATE, s, r))

        s, r = _score_personal_loan_candidate(
            signals.is_employed, signals.financial_distress_score
        )
        scoring_map.append((LendingTag.PERSONAL_LOAN_CANDIDATE, s, r))

        s, r = _score_mortgage_candidate(signals.has_property, signals.income_estimate)
        scoring_map.append((LendingTag.MORTGAGE_CANDIDATE, s, r))

        s, r = _score_refinance_candidate(signals.has_property, signals.financial_distress_score)
        scoring_map.append((LendingTag.REFINANCE_CANDIDATE, s, r))

        s, r = _score_debt_consolidation(
            signals.financial_distress_score,
            signals.criminal_count,
            signals.has_vehicle,
            signals.has_property,
        )
        scoring_map.append((LendingTag.DEBT_CONSOLIDATION, s, r))

        results: list[TagResult] = []
        for tag, confidence, reasoning in scoring_map:
            threshold = _THRESHOLDS.get(tag, 0.65)
            if confidence >= threshold and reasoning:
                results.append(
                    TagResult(
                        tag=tag,
                        confidence=round(confidence, 4),
                        reasoning=reasoning,
                        scored_at=now,
                    )
                )

        return results
```

- [ ] **Run → Expected PASS:**

```
python3 -m pytest tests/test_enrichers/test_commercial_tags.py -v -k "commercial_engine"
# 5 passed
```

- [ ] **Commit:**

```bash
git add modules/enrichers/commercial_tagger.py
git commit -m "feat(phase4): add CommercialTagsEngine with full scoring pipeline over PersonSignals"
```

---

## Task 8: `CommercialTaggerDaemon` — Background Batch Processor

**Files:**
- Modify: `modules/enrichers/commercial_tagger.py`

**What:** Add `CommercialTaggerDaemon` class with `start()`, `stop()`, and `_run_batch()` methods. Daemon queries `Person` rows where `last_scraped_at > self._last_run_at` (newly enriched since last cycle), assembles `PersonSignals` for each, runs `CommercialTagsEngine.tag_person()`, and upserts `MarketingTag` rows. Sleeps 15 minutes between batches. Uses `async_session_factory` for its own sessions.

- [ ] **Write failing test** — append to `tests/test_enrichers/test_commercial_tags.py`:

```python
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from modules.enrichers.commercial_tagger import CommercialTaggerDaemon


def test_daemon_instantiates():
    daemon = CommercialTaggerDaemon()
    assert not daemon._running


@pytest.mark.asyncio
async def test_daemon_stop_sets_running_false():
    daemon = CommercialTaggerDaemon()
    daemon._running = True
    daemon.stop()
    assert not daemon._running


@pytest.mark.asyncio
async def test_daemon_run_batch_calls_engine(monkeypatch):
    """_run_batch with no persons in DB completes without error."""
    daemon = CommercialTaggerDaemon()

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)

    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "modules.enrichers.commercial_tagger.async_session_factory",
        return_value=mock_ctx,
    ):
        await daemon._run_batch()  # must not raise
```

- [ ] **Run → Expected FAIL:**

```
python3 -m pytest tests/test_enrichers/test_commercial_tags.py -v -k "daemon"
# ImportError: cannot import name 'CommercialTaggerDaemon' ...
```

- [ ] **Implement** — append to `modules/enrichers/commercial_tagger.py`:

```python
# ─── CommercialTaggerDaemon ────────────────────────────────────────────────────

_BATCH_SIZE = 50
_SLEEP_SECONDS = 900  # 15 minutes


class CommercialTaggerDaemon:
    """Background daemon: tags newly enriched persons with commercial signals."""

    def __init__(self) -> None:
        self._running = False
        self._last_run_at: datetime = datetime.min.replace(tzinfo=UTC)
        self._engine = CommercialTagsEngine()

    def stop(self) -> None:
        self._running = False

    async def start(self) -> None:
        self._running = True
        logger.info("CommercialTaggerDaemon started")
        while self._running:
            try:
                await self._run_batch()
            except Exception:
                logger.exception("CommercialTaggerDaemon batch error")
            await asyncio.sleep(_SLEEP_SECONDS)

    async def _run_batch(self) -> None:
        cutoff = self._last_run_at
        run_started = datetime.now(UTC)

        async with async_session_factory() as session:
            persons = list(
                (
                    await session.execute(
                        select(Person)
                        .where(
                            Person.last_scraped_at.isnot(None),
                            Person.last_scraped_at > cutoff,
                        )
                        .order_by(Person.last_scraped_at.asc())
                        .limit(_BATCH_SIZE)
                    )
                )
                .scalars()
                .all()
            )

        if not persons:
            self._last_run_at = run_started
            return

        logger.info("CommercialTaggerDaemon: processing %d persons", len(persons))

        for person in persons:
            try:
                async with async_session_factory() as session:
                    signals = await assemble_person_signals(person.id, session)
                    tag_results = self._engine.tag_person(signals)
                    await _upsert_commercial_tags(person.id, tag_results, session)
                    await session.commit()
            except Exception:
                logger.exception("CommercialTaggerDaemon: failed person_id=%s", person.id)

        self._last_run_at = run_started
        logger.info("CommercialTaggerDaemon: batch complete, last_run_at=%s", self._last_run_at)


async def _upsert_commercial_tags(
    person_id: UUID,
    tag_results: list[TagResult],
    session: AsyncSession,
) -> None:
    for result in tag_results:
        existing = (
            (
                await session.execute(
                    select(MarketingTag).where(
                        MarketingTag.person_id == person_id,
                        MarketingTag.tag == result.tag,
                    )
                )
            )
            .scalars()
            .first()
        )

        category = _COMMERCIAL_TAG_CATEGORY.get(result.tag)

        if existing:
            existing.confidence = result.confidence
            existing.reasoning = result.reasoning
            existing.scored_at = result.scored_at
            existing.tag_category = category
        else:
            session.add(
                MarketingTag(
                    person_id=person_id,
                    tag=result.tag,
                    confidence=result.confidence,
                    reasoning=result.reasoning,
                    scored_at=result.scored_at,
                    tag_category=category,
                )
            )
```

- [ ] **Run → Expected PASS:**

```
python3 -m pytest tests/test_enrichers/test_commercial_tags.py -v -k "daemon"
# 3 passed
```

- [ ] **Commit:**

```bash
git add modules/enrichers/commercial_tagger.py
git commit -m "feat(phase4): add CommercialTaggerDaemon with 15-min batch loop and upsert logic"
```

---

## Task 9: New API Endpoints — `GET /tags/summary` and `POST /tags/batch`

**Files:**
- Modify: `api/routes/marketing.py`

**What:** Add two new routes to the existing `marketing.py` router. The existing `POST /persons/{id}/tag` and `GET /persons/{id}/tags` routes are already implemented — do not touch them. Only add the two missing routes.

- `GET /tags/summary` — aggregates `{tag: count}` across all `MarketingTag` rows using a `GROUP BY` query.
- `POST /tags/batch` — triggers `CommercialTaggerDaemon._run_batch()` immediately (one-shot, not the loop) and returns a count of persons processed.

- [ ] **Write failing test** — `tests/test_api/test_commercial_tags_api.py` (create this file):

```python
"""API tests for Phase 4 commercial tags endpoints."""

import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_tags_summary_returns_dict(monkeypatch):
    """GET /tags/summary returns {tag: count} dict."""
    from api.routes.marketing import router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router, prefix="/persons")

    mock_session = AsyncMock(spec=AsyncSession)
    mock_rows = [("auto_loan_candidate", 5), ("insurance_auto", 3)]
    mock_result = MagicMock()
    mock_result.all.return_value = mock_rows
    mock_session.execute = AsyncMock(return_value=mock_result)

    from api.deps import DbDep
    app.dependency_overrides[DbDep] = lambda: mock_session

    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get("/persons/tags/summary")

    assert resp.status_code == 200
    data = resp.json()
    assert "summary" in data
    assert isinstance(data["summary"], dict)


@pytest.mark.asyncio
async def test_tags_batch_triggers_run(monkeypatch):
    """POST /tags/batch triggers daemon batch and returns processed count."""
    from api.routes.marketing import router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router, prefix="/persons")

    mock_session = AsyncMock(spec=AsyncSession)
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)

    from api.deps import DbDep
    app.dependency_overrides[DbDep] = lambda: mock_session

    with patch(
        "api.routes.marketing._commercial_daemon._run_batch",
        new_callable=AsyncMock,
    ):
        async with AsyncClient(app=app, base_url="http://test") as client:
            resp = await client.post("/persons/tags/batch")

    assert resp.status_code == 200
    assert "triggered" in resp.json()
```

- [ ] **Run → Expected FAIL:**

```
python3 -m pytest tests/test_api/test_commercial_tags_api.py -v
# ImportError or 404 — routes not yet defined
```

- [ ] **Implement** — add to `api/routes/marketing.py` (after existing imports and before the first `@router` decorator, add the new import; then append the two new routes at the bottom):

Add to imports:
```python
from sqlalchemy import func as sa_func

from modules.enrichers.commercial_tagger import CommercialTaggerDaemon

_commercial_daemon = CommercialTaggerDaemon()
```

Add new routes:
```python
@router.get("/tags/summary")
async def get_tags_summary(session: AsyncSession = DbDep):
    """Return {tag: count} aggregation across all MarketingTag rows."""
    rows = (
        await session.execute(
            select(MarketingTag.tag, sa_func.count(MarketingTag.id).label("cnt"))
            .group_by(MarketingTag.tag)
            .order_by(sa_func.count(MarketingTag.id).desc())
        )
    ).all()

    return {
        "summary": {row.tag: row.cnt for row in rows},
        "total_unique_tags": len(rows),
    }


@router.post("/tags/batch")
async def trigger_batch_tagging(session: AsyncSession = DbDep):
    """Trigger CommercialTaggerDaemon._run_batch() immediately (one-shot)."""
    try:
        await _commercial_daemon._run_batch()
    except Exception as exc:
        logger.exception("Batch tagging failed")
        raise HTTPException(500, "Batch tagging error") from exc

    return {"triggered": True, "message": "Commercial tag batch complete"}
```

- [ ] **Run → Expected PASS:**

```
python3 -m pytest tests/test_api/test_commercial_tags_api.py -v
# 2 passed
```

- [ ] **Commit:**

```bash
git add api/routes/marketing.py tests/test_api/test_commercial_tags_api.py
git commit -m "feat(phase4): add GET /tags/summary and POST /tags/batch API endpoints"
```

---

## Task 10: Register `CommercialTaggerDaemon` in `worker.py`

**Files:**
- Modify: `worker.py`

**What:** Import `CommercialTaggerDaemon` and add it to the `tasks` list in `main()`, after the freshness scheduler block. Add a `--no-commercial` CLI flag mirroring the existing `--no-growth` / `--no-freshness` pattern.

- [ ] **Write failing test** — `tests/test_daemon/test_commercial_daemon_worker.py` (create this file):

```python
"""Verify CommercialTaggerDaemon can be imported and integrated."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import asyncio


def test_commercial_tagger_daemon_importable():
    from modules.enrichers.commercial_tagger import CommercialTaggerDaemon
    daemon = CommercialTaggerDaemon()
    assert hasattr(daemon, "start")
    assert hasattr(daemon, "stop")
    assert hasattr(daemon, "_run_batch")


@pytest.mark.asyncio
async def test_daemon_start_stops_cleanly():
    from modules.enrichers.commercial_tagger import CommercialTaggerDaemon

    daemon = CommercialTaggerDaemon()

    async def _stop_after_one_cycle():
        await asyncio.sleep(0.05)
        daemon.stop()

    with patch.object(daemon, "_run_batch", new_callable=AsyncMock) as mock_batch:
        with patch("modules.enrichers.commercial_tagger._SLEEP_SECONDS", 0):
            stopper = asyncio.create_task(_stop_after_one_cycle())
            runner = asyncio.create_task(daemon.start())
            await asyncio.gather(stopper, runner, return_exceptions=True)

    assert mock_batch.call_count >= 1


def test_worker_has_no_commercial_flag():
    """worker.py argparse must accept --no-commercial flag."""
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, "worker.py", "--help"],
        capture_output=True,
        text=True,
        cwd="/home/wolf/Lycan-Data",
    )
    assert "--no-commercial" in result.stdout
```

- [ ] **Run → Expected FAIL:**

```
python3 -m pytest tests/test_daemon/test_commercial_daemon_worker.py -v
# test_worker_has_no_commercial_flag: AssertionError (--no-commercial not in help)
```

- [ ] **Implement** — modify `worker.py`:

Add import at the top of `main()` function alongside existing imports:
```python
from modules.enrichers.commercial_tagger import CommercialTaggerDaemon
```

Add after the freshness scheduler block:
```python
    # Commercial tagger daemon
    if enable_commercial:
        ct = CommercialTaggerDaemon()
        tasks.append(asyncio.create_task(ct.start(), name="commercial-tagger"))
        logger.info("Started commercial tagger daemon")
```

Update the `main()` signature and log line:
```python
async def main(workers: int, enable_growth: bool, enable_freshness: bool, enable_commercial: bool):
    ...
    logger.info(
        f"Worker running — {workers} dispatcher(s) + "
        f"{'growth daemon + ' if enable_growth else ''}"
        f"{'freshness scheduler + ' if enable_freshness else ''}"
        f"{'commercial tagger' if enable_commercial else ''}"
    )
```

Add CLI arg at the bottom:
```python
    parser.add_argument("--no-commercial", action="store_true", help="Disable commercial tagger daemon")
    ...
    asyncio.run(
        main(
            workers=args.workers,
            enable_growth=not args.no_growth,
            enable_freshness=not args.no_freshness,
            enable_commercial=not args.no_commercial,
        )
    )
```

- [ ] **Run → Expected PASS:**

```
python3 -m pytest tests/test_daemon/test_commercial_daemon_worker.py -v
# 3 passed
```

- [ ] **Commit:**

```bash
git add worker.py tests/test_daemon/test_commercial_daemon_worker.py
git commit -m "feat(phase4): register CommercialTaggerDaemon in worker.py with --no-commercial flag"
```

---

## Task 11: Full Suite Green Check

**Files:**
- No new files

**What:** Run the full test suite to confirm Phase 4 additions haven't broken any existing tests. Fix any regressions before marking complete.

Key regression risk: renaming `LendingTag.MORTGAGE_READY` to `MORTGAGE_CANDIDATE`. Search for any existing test or code referencing `MORTGAGE_READY` and update.

- [ ] **Check for MORTGAGE_READY references:**

```bash
grep -r "MORTGAGE_READY\|mortgage_ready" /home/wolf/Lycan-Data --include="*.py" -l
```

- [ ] **Update any references found** — change `MORTGAGE_READY` → `MORTGAGE_CANDIDATE` and `"mortgage_ready"` → `"mortgage"` in each file found.

- [ ] **Run full suite:**

```
python3 -m pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected output ends with:
```
============================================================
X passed, 0 failed, Y warnings
============================================================
```

- [ ] **Fix any failures** before committing.

- [ ] **Commit:**

```bash
git add -u
git commit -m "fix(phase4): resolve MORTGAGE_READY regressions and confirm full suite green"
```

---

## Completion Checklist

- [ ] Task 1: `InsuranceTag`, `BankingTag`, `WealthTag` StrEnums added; `MORTGAGE_CANDIDATE` renamed
- [ ] Task 2: `_THRESHOLDS` extended with all 12 new entries
- [ ] Task 3: `_score_insurance_auto/life/health` implemented and tested
- [ ] Task 4: `_score_banking_basic/premium` and `_score_high_net_worth` implemented and tested
- [ ] Task 5: Six new lending scorers implemented and tested
- [ ] Task 6: `PersonSignals` dataclass and `assemble_person_signals()` in `commercial_tagger.py`
- [ ] Task 7: `CommercialTagsEngine.tag_person()` wires all 12 scorers to `PersonSignals`
- [ ] Task 8: `CommercialTaggerDaemon` with 15-min loop and DB upsert
- [ ] Task 9: `GET /tags/summary` and `POST /tags/batch` routes in `api/routes/marketing.py`
- [ ] Task 10: Daemon registered in `worker.py` with `--no-commercial` flag
- [ ] Task 11: Full test suite green, no regressions
