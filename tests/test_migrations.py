import pytest
from sqlalchemy import text

from shared.db import get_test_db

EXPECTED_TABLES = [
    "persons",
    "aliases",
    "identifiers",
    "relationships",
    "relationship_score_history",
    "social_profiles",
    "webs",
    "web_memberships",
    "data_sources",
    "crawl_jobs",
    "crawl_logs",
    "alerts",
    "addresses",
    "employment_history",
    "education",
    "breach_records",
    "media_assets",
    "watchlist_matches",
    "behavioural_profiles",
    "behavioural_signals",
    "burner_assessments",
    "darkweb_mentions",
    "crypto_wallets",
    "crypto_transactions",
    "credit_risk_assessments",
    "wealth_assessments",
    "data_quality_log",
    "freshness_queue",
]


@pytest.mark.asyncio
async def test_all_tables_exist():
    """Verify all 28 tables are present in the database."""
    async for session in get_test_db():
        for table in EXPECTED_TABLES:
            result = await session.execute(text(f"SELECT to_regclass('public.{table}')"))
            val = result.scalar()
            assert val is not None, f"Table '{table}' not found in database"


def test_new_migration_revision_exists():
    """Verify migration for dedup_reviews/merged_into exists in versions directory."""
    import pathlib

    versions_path = pathlib.Path("migrations/versions")
    revisions = [f.stem for f in versions_path.glob("*.py") if not f.stem.startswith("__")]
    assert any("dedup_reviews" in r or "merged_into" in r for r in revisions), (
        "Expected migration for dedup_reviews/merged_into not found"
    )
