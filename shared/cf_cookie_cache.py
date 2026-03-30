"""Cache Cloudflare clearance cookies in Garnet (Redis) to avoid re-solving challenges."""

import json
import logging

from shared.cache import get_cache

logger = logging.getLogger(__name__)
CF_COOKIE_TTL = 1800  # 30 minutes — cf_clearance cookies typically last 30 min


async def get_cf_cookies(domain: str) -> dict | None:
    """Retrieve cached CF cookies for a domain. Returns None if expired or missing."""
    try:
        r = await get_cache()
        raw = await r.get(f"cf_cookies:{domain}")
        return json.loads(raw) if raw else None
    except Exception:
        return None


async def set_cf_cookies(domain: str, cookies: dict) -> None:
    """Cache CF cookies for domain with 30-min TTL."""
    try:
        r = await get_cache()
        await r.set(f"cf_cookies:{domain}", json.dumps(cookies), ex=CF_COOKIE_TTL)
        logger.debug("Cached CF cookies for %s (TTL %ds)", domain, CF_COOKIE_TTL)
    except Exception:
        logger.warning("Failed to cache CF cookies for %s", domain)
