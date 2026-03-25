from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from modules.crawlers.base import BaseCrawler
    from modules.crawlers.core.models import CrawlerCategory

# Registry: platform_name → crawler class
CRAWLER_REGISTRY: dict[str, type[BaseCrawler]] = {}


def register(platform: str):
    """Decorator that registers a crawler class for a platform."""

    def decorator(cls: type[BaseCrawler]) -> type[BaseCrawler]:
        CRAWLER_REGISTRY[platform.lower()] = cls
        return cls

    return decorator


def get_crawler(platform: str) -> type[BaseCrawler] | None:
    """Look up crawler by platform name. Case-insensitive."""
    return CRAWLER_REGISTRY.get(platform.lower())


def list_platforms() -> list[str]:
    """Return all registered platform names."""
    return sorted(CRAWLER_REGISTRY.keys())


def is_registered(platform: str) -> bool:
    return platform.lower() in CRAWLER_REGISTRY


def get_crawlers_by_category(category: CrawlerCategory) -> dict[str, type[BaseCrawler]]:
    """Return all registered crawlers matching a category."""
    return {
        name: cls
        for name, cls in CRAWLER_REGISTRY.items()
        if getattr(cls, "category", None) == category
    }


def list_categories() -> list[str]:
    """Return all unique categories from registered crawlers."""
    cats = {getattr(cls, "category", None) for cls in CRAWLER_REGISTRY.values()}
    return sorted(str(c) for c in cats if c is not None)


def registry_stats() -> dict[str, int]:
    """Return crawler counts per category."""
    from collections import Counter

    return dict(
        Counter(
            str(getattr(cls, "category", "unknown"))
            for cls in CRAWLER_REGISTRY.values()
        )
    )
