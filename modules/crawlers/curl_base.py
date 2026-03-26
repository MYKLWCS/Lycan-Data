"""
CurlCrawler — extends HttpxCrawler with Chrome 124 TLS fingerprint impersonation.

Uses curl_cffi.requests.AsyncSession instead of httpx. Impersonates Chrome 124
at the TLS handshake level, bypassing TLS fingerprinting by Cloudflare, DataDome,
Akamai, and similar services that reject Python's default TLS signature.

Drop-in replacement: subclasses only change their parent import from
HttpxCrawler to CurlCrawler. The scrape() method is unchanged.
"""

from __future__ import annotations

import logging

from modules.crawlers.httpx_base import HttpxCrawler

logger = logging.getLogger(__name__)


class CurlCrawler(HttpxCrawler):
    """HttpxCrawler variant that impersonates Chrome 124 at the TLS layer."""

    _IMPERSONATE = "chrome124"

    async def get(self, url: str, **kwargs):
        """GET via curl_cffi AsyncSession with Chrome 124 TLS fingerprint."""
        try:
            from curl_cffi.requests import AsyncSession

            proxy = self.get_proxy()
            proxies = {"http": proxy, "https": proxy} if proxy else None
            async with AsyncSession(impersonate=self._IMPERSONATE) as session:
                resp = await session.get(url, proxies=proxies, **kwargs)
                resp.raise_for_status()
                return resp
        except ImportError:
            logger.warning("curl_cffi not available, falling back to httpx")
            return await super().get(url, **kwargs)
        except Exception as exc:
            logger.warning("curl_cffi GET failed for %s: %s", url, exc)
            return None

    async def post(self, url: str, **kwargs):
        """POST via curl_cffi AsyncSession with Chrome 124 TLS fingerprint."""
        try:
            from curl_cffi.requests import AsyncSession

            proxy = self.get_proxy()
            proxies = {"http": proxy, "https": proxy} if proxy else None
            async with AsyncSession(impersonate=self._IMPERSONATE) as session:
                resp = await session.post(url, proxies=proxies, **kwargs)
                resp.raise_for_status()
                return resp
        except ImportError:
            logger.warning("curl_cffi not available, falling back to httpx")
            return await super().post(url, **kwargs)
        except Exception as exc:
            logger.warning("curl_cffi POST failed for %s: %s", url, exc)
            return None
