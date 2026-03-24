"""Temporal pattern analysis — SQL window functions, no external dependencies."""
import logging
from typing import Any

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class TemporalPatternAnalyzer:
    """
    Detects temporal patterns in entity data using PostgreSQL window functions.
    All queries are read-only.
    """

    async def detect_change_velocity(
        self, person_id: str, session: AsyncSession, window_days: int = 30
    ) -> list[dict[str, Any]]:
        """
        Detect how fast a person's records are changing.
        Uses crawl_jobs as a proxy for entity activity.
        """
        try:
            result = await session.execute(
                sa_text("""
                    SELECT
                        DATE_TRUNC('day', created_at) AS date,
                        COUNT(*) AS jobs_per_day,
                        COUNT(DISTINCT platform) AS platforms_per_day,
                        CASE
                            WHEN COUNT(*) > 20 THEN 'VERY_HIGH'
                            WHEN COUNT(*) > 10 THEN 'HIGH'
                            WHEN COUNT(*) > 5  THEN 'MEDIUM'
                            ELSE 'LOW'
                        END AS velocity
                    FROM crawl_jobs
                    WHERE person_id = :person_id
                      AND created_at >= NOW() - make_interval(days => :days)
                    GROUP BY DATE_TRUNC('day', created_at)
                    ORDER BY date DESC
                    LIMIT 90
                """),
                {"person_id": person_id, "days": window_days},
            )
            return [dict(row) for row in result.mappings().all()]
        except Exception:
            logger.exception("detect_change_velocity failed person_id=%s", person_id)
            return []

    async def find_address_change_patterns(
        self, session: AsyncSession, min_changes: int = 3, limit: int = 50
    ) -> list[dict[str, Any]]:
        """
        Find persons with unusually high address change frequency (relocation anomaly).
        """
        try:
            result = await session.execute(
                sa_text("""
                    SELECT
                        person_id::text,
                        COUNT(*) AS address_count,
                        COUNT(DISTINCT city) AS distinct_cities,
                        COUNT(DISTINCT state) AS distinct_states,
                        MIN(created_at) AS first_seen,
                        MAX(created_at) AS last_seen
                    FROM addresses
                    GROUP BY person_id
                    HAVING COUNT(*) >= :min_changes
                    ORDER BY address_count DESC
                    LIMIT :limit
                """),
                {"min_changes": min_changes, "limit": limit},
            )
            return [dict(row) for row in result.mappings().all()]
        except Exception:
            logger.exception("find_address_change_patterns failed")
            return []

    async def find_identifier_change_patterns(
        self, session: AsyncSession, min_changes: int = 3, limit: int = 50
    ) -> list[dict[str, Any]]:
        """
        Find persons with many identifier changes (phone/email churn — burner indicator).
        """
        try:
            result = await session.execute(
                sa_text("""
                    SELECT
                        person_id::text,
                        type,
                        COUNT(*) AS identifier_count,
                        COUNT(DISTINCT value) AS distinct_values
                    FROM identifiers
                    WHERE type IN ('phone', 'email')
                    GROUP BY person_id, type
                    HAVING COUNT(DISTINCT value) >= :min_changes
                    ORDER BY identifier_count DESC
                    LIMIT :limit
                """),
                {"min_changes": min_changes, "limit": limit},
            )
            return [dict(row) for row in result.mappings().all()]
        except Exception:
            logger.exception("find_identifier_change_patterns failed")
            return []

    async def find_co_occurring_risk_flags(
        self, session: AsyncSession, limit: int = 50
    ) -> list[dict[str, Any]]:
        """
        Find persons who appear in multiple risk tables simultaneously
        (watchlist + dark web + breach = high risk).
        """
        try:
            result = await session.execute(
                sa_text("""
                    SELECT
                        p.id::text AS person_id,
                        p.full_name,
                        COUNT(DISTINCT wm.id) AS watchlist_hits,
                        COUNT(DISTINCT dm.id) AS darkweb_hits,
                        COUNT(DISTINCT br.id) AS breach_hits,
                        COUNT(DISTINCT wm.id) + COUNT(DISTINCT dm.id) + COUNT(DISTINCT br.id) AS total_flags
                    FROM persons p
                    LEFT JOIN watchlist_matches wm ON wm.person_id = p.id
                    LEFT JOIN darkweb_mentions dm ON dm.person_id = p.id
                    LEFT JOIN breach_records br ON br.person_id = p.id
                    GROUP BY p.id, p.full_name
                    HAVING (COUNT(DISTINCT wm.id) + COUNT(DISTINCT dm.id) + COUNT(DISTINCT br.id)) >= 2
                    ORDER BY total_flags DESC
                    LIMIT :limit
                """),
                {"limit": limit},
            )
            return [dict(row) for row in result.mappings().all()]
        except Exception:
            logger.exception("find_co_occurring_risk_flags failed")
            return []

    async def find_network_anomalies(
        self, session: AsyncSession, min_connections: int = 10, limit: int = 50
    ) -> list[dict[str, Any]]:
        """
        Find persons with an unusually high number of relationships (network hubs).
        High connectivity can indicate fraud rings or persons of interest.
        """
        try:
            result = await session.execute(
                sa_text("""
                    SELECT
                        person_id_a::text AS person_id,
                        COUNT(DISTINCT person_id_b) AS connection_count,
                        COUNT(DISTINCT relationship_type) AS relationship_types
                    FROM relationships
                    GROUP BY person_id_a
                    HAVING COUNT(DISTINCT person_id_b) >= :min_connections
                    ORDER BY connection_count DESC
                    LIMIT :limit
                """),
                {"min_connections": min_connections, "limit": limit},
            )
            return [dict(row) for row in result.mappings().all()]
        except Exception:
            logger.exception("find_network_anomalies failed")
            return []
