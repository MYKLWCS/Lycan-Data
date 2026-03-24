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
