import pytest
from modules.crawlers.playwright_base import PlaywrightBaseCrawler


def test_uses_patchright_import():
    import inspect
    import modules.crawlers.playwright_base as m

    src = inspect.getsource(m)
    assert "patchright" in src
    assert "playwright" not in src.split("patchright")[0]


def test_ua_is_chrome_130_plus():
    ua = PlaywrightBaseCrawler.USER_AGENTS[0]
    version = int(ua.split("Chrome/")[1].split(".")[0])
    assert version >= 130
