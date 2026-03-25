from modules.crawlers.base import BaseCrawler
from modules.crawlers.camoufox_base import CamoufoxCrawler


def test_camoufox_is_base_subclass():
    assert issubclass(CamoufoxCrawler, BaseCrawler)


def test_camoufox_has_get_page():
    assert hasattr(CamoufoxCrawler, "get_page")
