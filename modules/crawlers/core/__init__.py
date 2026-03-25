"""
crawlers.core — Base classes, models, and orchestration for the crawler framework.

All scrapers extend BaseCrawler from this package. New scrapers register via
the @register decorator and are auto-discovered by the ScraperOrchestrator.
"""

from modules.crawlers.core.models import (
    CrawlerCategory,
    CrawlerHealth,
    RateLimit,
)
from modules.crawlers.core.result import CrawlerResult as StandardCrawlerResult
from modules.crawlers.core.orchestrator import ScraperOrchestrator

__all__ = [
    "CrawlerCategory",
    "CrawlerHealth",
    "RateLimit",
    "StandardCrawlerResult",
    "ScraperOrchestrator",
]
