"""
Open Discovery Orchestrator.

Runs all Track 2 discovery tools in parallel against a query (name, domain,
username, or email). De-duplicates hits by URL and writes new ones to the
source_discovery_log table.

Self-improvement loop:
  - Sites that have been approved and have high crawl_success_rate are
    surfaced first in the review queue.
  - Sites whose URL base-domain already exists in data_sources are skipped.
"""

from __future__ import annotations

import asyncio
import logging
import urllib.parse
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.discovery.base import DiscoveryHit
from modules.discovery.tools import ALL_TOOLS, BaseDiscoveryTool
from shared.models.crawl import DataSource
from shared.models.discovery import DiscoveredSource

logger = logging.getLogger(__name__)


async def run_discovery(
    query: str,
    session: AsyncSession,
    *,
    tool_names: list[str] | None = None,
    on_progress: object | None = None,
) -> dict:
    """
    Run all (or a subset of) discovery tools against *query*.

    Writes new hits to source_discovery_log. Returns a summary dict.

    Args:
        query:       Free-text search target (person name, domain, username…)
        session:     Async SQLAlchemy session
        tool_names:  Optional whitelist of tool names to run
        on_progress: Optional async callable(dict) for live progress events
    """
    started_at = datetime.now(UTC)

    # Instantiate tools
    tools: list[BaseDiscoveryTool] = []
    for cls in ALL_TOOLS:
        instance = cls()
        if tool_names is None or instance.tool_name in tool_names:
            tools.append(instance)

    logger.info("Discovery run: query=%r tools=%s", query, [t.tool_name for t in tools])

    # Run all tools concurrently
    all_hits: list[DiscoveryHit] = []
    tool_stats: dict[str, int] = {}

    async def _run_one(tool: BaseDiscoveryTool) -> list[DiscoveryHit]:
        try:
            hits = await tool.run(query)
            tool_stats[tool.tool_name] = len(hits)
            logger.info("%s returned %d hits", tool.tool_name, len(hits))
            if on_progress:
                cb = on_progress({"tool": tool.tool_name, "hits": len(hits)})
                if asyncio.iscoroutine(cb):
                    await cb
            return hits
        except Exception as exc:
            logger.warning("%s crashed: %s", tool.tool_name, exc)
            tool_stats[tool.tool_name] = 0
            return []

    results = await asyncio.gather(*[_run_one(t) for t in tools])
    for batch in results:
        all_hits.extend(batch)

    # De-duplicate by normalised URL
    seen_urls: set[str] = set()
    unique_hits: list[DiscoveryHit] = []
    for hit in all_hits:
        norm = _normalise_url(hit.url)
        if norm not in seen_urls:
            seen_urls.add(norm)
            unique_hits.append(hit)

    # Filter out URLs already in data_sources
    existing_bases = await _existing_source_bases(session)

    new_hits: list[DiscoveryHit] = []
    skipped = 0
    for hit in unique_hits:
        base = _url_base(hit.url)
        if base in existing_bases:
            skipped += 1
            continue
        new_hits.append(hit)

    # Persist new hits
    written = 0
    for hit in new_hits:
        # Check not already in discovery log
        exists = await session.execute(
            select(DiscoveredSource).where(DiscoveredSource.url == hit.url).limit(1)
        )
        if exists.scalar_one_or_none():
            continue

        row = DiscoveredSource(
            name=hit.name[:512],
            url=hit.url[:2048],
            category=hit.category,
            discovered_by=hit.discovered_by,
            discovery_query=hit.discovery_query[:1024] if hit.discovery_query else None,
            raw_context=hit.raw_context,
            data_quality_estimate=hit.data_quality_estimate,
            legal_risk=hit.legal_risk,
            data_types=hit.data_types or None,
            proposed_pattern=hit.proposed_pattern,
        )
        session.add(row)
        written += 1

    await session.commit()

    # Auto-queue crawl jobs for discovered URLs that match registered crawlers
    auto_queued = await _auto_queue_discovered(new_hits, session)

    elapsed = (datetime.now(UTC) - started_at).total_seconds()
    summary = {
        "query": query,
        "tools_run": len(tools),
        "total_hits": len(all_hits),
        "unique_hits": len(unique_hits),
        "skipped_existing": skipped,
        "written_to_queue": written,
        "auto_queued_crawls": auto_queued,
        "elapsed_seconds": round(elapsed, 2),
        "tool_stats": tool_stats,
    }
    logger.info("Discovery complete: %s", summary)
    return summary


async def _auto_queue_discovered(hits: list[DiscoveryHit], session: AsyncSession) -> int:
    """Queue crawl jobs for discovered URLs that match registered crawlers."""
    from modules.crawlers.registry import get_crawler
    from shared.events import event_bus

    URL_TO_CRAWLER = {
        "twitter.com": "social_twitter",
        "x.com": "social_twitter",
        "linkedin.com": "social_linkedin",
        "instagram.com": "social_instagram",
        "facebook.com": "social_facebook",
        "github.com": "github_profile",
        "reddit.com": "reddit",
        "tiktok.com": "social_tiktok",
        "youtube.com": "social_youtube",
        "pinterest.com": "social_pinterest",
        "telegram.org": "telegram",
        "t.me": "telegram",
        "discord.gg": "discord",
        "twitch.tv": "social_twitch",
        "snapchat.com": "social_snapchat",
        "threads.net": "social_threads",
        "bsky.app": "social_bluesky",
        "truthsocial.com": "social_truthsocial",
        "vk.com": "social_vk",
        "steamcommunity.com": "social_steam",
    }

    queued = 0
    for hit in hits:
        if not hit.url:
            continue
        domain = urllib.parse.urlparse(hit.url).netloc.replace("www.", "")
        crawler_name = None
        for pattern, name in URL_TO_CRAWLER.items():
            if domain == pattern or domain.endswith("." + pattern):
                crawler_name = name
                break
        if crawler_name and get_crawler(crawler_name):
            await event_bus.enqueue(
                {
                    "platform": crawler_name,
                    "identifier": hit.url,
                    "priority": "normal",
                },
                priority="normal",
            )
            queued += 1
            logger.info(
                "Auto-queued %s crawl for discovered URL: %s",
                crawler_name,
                hit.url,
            )
        else:
            # Fallback: queue generic web scraper for unmapped URLs
            if (
                hit.url
                and hit.url.startswith("http")
                and not any(skip in hit.url for skip in [".pdf", ".jpg", ".png", ".mp4"])
            ):
                await event_bus.enqueue(
                    {
                        "platform": "generic_web_scraper",
                        "identifier": hit.url,
                        "person_id": "",
                        "priority": "low",
                    },
                    priority="low",
                )
                queued += 1
                logger.info(
                    "Auto-queued generic_web_scraper for unmapped URL: %s",
                    hit.url,
                )
    return queued


async def _existing_source_bases(session: AsyncSession) -> set[str]:
    """Return the set of normalised base-domains already in data_sources."""
    result = await session.execute(select(DataSource.base_url))
    bases: set[str] = set()
    for (url,) in result:
        if url:
            bases.add(_url_base(url))
    return bases


def _normalise_url(url: str) -> str:
    try:
        p = urllib.parse.urlparse(url.lower().rstrip("/"))
        return f"{p.netloc}{p.path}"
    except Exception:
        return url.lower()


def _url_base(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return url.lower()
