from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from modules.crawlers.base import BaseCrawler

# Registry: platform_name → crawler class
CRAWLER_REGISTRY: dict[str, type["BaseCrawler"]] = {}


def register(platform: str):
    """Decorator that registers a crawler class for a platform."""
    def decorator(cls: type["BaseCrawler"]) -> type["BaseCrawler"]:
        CRAWLER_REGISTRY[platform.lower()] = cls
        return cls
    return decorator


def get_crawler(platform: str) -> type["BaseCrawler"] | None:
    """Look up crawler by platform name. Case-insensitive."""
    return CRAWLER_REGISTRY.get(platform.lower())


def list_platforms() -> list[str]:
    """Return all registered platform names."""
    return sorted(CRAWLER_REGISTRY.keys())


def is_registered(platform: str) -> bool:
    return platform.lower() in CRAWLER_REGISTRY
