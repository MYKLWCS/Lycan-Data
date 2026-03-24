"""
Scrapy downloader middleware that routes all requests through Tor.
Add to settings.py in each Scrapy spider:

    DOWNLOADER_MIDDLEWARES = {
        'shared.scrapy_middleware.TorProxyMiddleware': 350,
    }
"""

import logging

from scrapy import signals
from scrapy.http import Request

from shared.config import settings
from shared.tor import tor_manager

logger = logging.getLogger(__name__)


class TorProxyMiddleware:
    """Routes Scrapy requests through Tor SOCKS5 proxy."""

    @classmethod
    def from_crawler(cls, crawler):
        mw = cls()
        crawler.signals.connect(mw.spider_opened, signal=signals.spider_opened)
        return mw

    def spider_opened(self, spider):
        logger.info("TorProxyMiddleware enabled for spider: %s", spider.name)

    def process_request(self, request: Request, spider):
        if not settings.tor_enabled:
            return None
        if request.meta.get("tor_disabled"):
            return None
        role = request.meta.get("tor_role", "spider")
        proxy = tor_manager.get_proxy_for_role(role)
        if proxy:
            request.meta["proxy"] = proxy
        return None

    def process_response(self, request, response, spider):
        return response

    def process_exception(self, request, exception, spider):
        return None
