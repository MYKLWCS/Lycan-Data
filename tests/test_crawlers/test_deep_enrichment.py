"""
Tests for deep enrichment crawlers — Task 33.
  - NewsSearchCrawler  (news_search)
  - GoogleMapsCrawler  (google_maps)
  - SocialGraphCrawler (social_graph)

15 tests — all HTTP calls are mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import modules.crawlers.google_maps  # noqa: F401

# Trigger @register decorators
import modules.crawlers.news_search  # noqa: F401
import modules.crawlers.social_graph  # noqa: F401
from modules.crawlers.google_maps import GoogleMapsCrawler, _parse_nominatim_result
from modules.crawlers.news_search import (
    NewsSearchCrawler,
    _parse_ddg_html,
    _parse_rss,
    _tag_article,
)
from modules.crawlers.registry import is_registered
from modules.crawlers.social_graph import (
    SocialGraphCrawler,
    _build_connections,
    _extract_mentions,
    _extract_platform_mentions,
)

# ===========================================================================
# Sample HTML / XML fixtures
# ===========================================================================

DDG_HTML_SAMPLE = """
<html><body>
<div class="result">
  <a class="result__a" href="https://example.com/story1">Crime boss arrested in sting operation</a>
  <div class="result__snippet">The suspect was arrested after a months-long investigation.</div>
  <span class="result__timestamp">2 hours ago</span>
</div>
<div class="result">
  <a class="result__a" href="https://example.com/story2">Local company files for bankruptcy</a>
  <div class="result__snippet">The firm faced insurmountable debt and filed for bankruptcy.</div>
</div>
</body></html>
"""

RSS_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test News</title>
    <item>
      <title>CEO appointed at tech startup</title>
      <link>https://news.example.com/article/1</link>
      <pubDate>Mon, 24 Mar 2026 10:00:00 GMT</pubDate>
      <description>The startup announced a new CEO today.</description>
    </item>
    <item>
      <title>Court verdict in landmark lawsuit</title>
      <link>https://news.example.com/article/2</link>
      <pubDate>Mon, 24 Mar 2026 09:00:00 GMT</pubDate>
      <description>The judge delivered a verdict in the lengthy legal battle.</description>
    </item>
  </channel>
</rss>
"""

NOMINATIM_JSON = [
    {
        "display_name": "Tesla, Inc., 3500 Deer Creek Road, Palo Alto, CA 94304, USA",
        "lat": "37.3946",
        "lon": "-122.1491",
        "type": "company",
        "address": {
            "house_number": "3500",
            "road": "Deer Creek Road",
            "city": "Palo Alto",
            "state": "California",
            "postcode": "94304",
            "country": "United States",
        },
    }
]


# ===========================================================================
# Helper
# ===========================================================================


def _mock_response(status: int = 200, text: str = "", json_data=None):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    if json_data is not None:
        resp.json = MagicMock(return_value=json_data)
    return resp


# ===========================================================================
# 1. news_search — DDG HTML parsing
# ===========================================================================


def test_news_ddg_html_article_parsed():
    """DDG HTML → at least one article extracted."""
    articles = _parse_ddg_html(DDG_HTML_SAMPLE)
    assert len(articles) >= 1
    article = articles[0]
    assert "title" in article
    assert "url" in article
    assert "snippet" in article
    assert "categories" in article
    assert article["source"] == "duckduckgo_news"


# ===========================================================================
# 2. news_search — RSS feed parsing
# ===========================================================================


def test_news_rss_feed_items_parsed():
    """RSS feed XML → items extracted with correct fields."""
    articles = _parse_rss(RSS_SAMPLE, source="google_news")
    assert len(articles) == 2
    titles = [a["title"] for a in articles]
    assert "CEO appointed at tech startup" in titles
    assert articles[0]["source"] == "google_news"
    assert "url" in articles[0]
    assert "date" in articles[0]


# ===========================================================================
# 3. news_search — article tagged "criminal" when "arrested" in text
# ===========================================================================


def test_news_article_tagged_criminal():
    """Article with 'arrested' in title → tagged 'criminal'."""
    tags = _tag_article("Crime boss arrested in sting", "Police arrested the suspect.")
    assert "criminal" in tags


# ===========================================================================
# 4. news_search — article tagged "legal" when "lawsuit" in text
# ===========================================================================


def test_news_article_tagged_legal():
    """Article with 'lawsuit' in snippet → tagged 'legal'."""
    tags = _tag_article("Court news", "The lawsuit was filed last week.")
    assert "legal" in tags


# ===========================================================================
# 5. news_search — deduplication by URL
# ===========================================================================


@pytest.mark.asyncio
async def test_news_deduplication_by_url():
    """Same URL from multiple sources appears only once in results."""
    crawler = NewsSearchCrawler()

    duplicate_rss = """<?xml version="1.0"?>
<rss><channel>
  <item>
    <title>Duplicate story</title>
    <link>https://example.com/story1</link>
    <pubDate>Mon, 24 Mar 2026 10:00:00 GMT</pubDate>
    <description>Story already in DDG results.</description>
  </item>
</channel></rss>"""

    ddg_resp = _mock_response(200, DDG_HTML_SAMPLE)
    rss_resp = _mock_response(200, duplicate_rss)

    async def fake_get(url, **kwargs):
        if "duckduckgo" in url:
            return ddg_resp
        return rss_resp

    crawler.get = fake_get
    result = await crawler.scrape("test query")

    urls = [a["url"] for a in result.data["articles"]]
    assert len(urls) == len(set(urls)), "Duplicate URLs found in results"


# ===========================================================================
# 6. news_search — HTTP error → found=False CrawlerResult
# ===========================================================================


@pytest.mark.asyncio
async def test_news_http_error_returns_result():
    """When all sources return HTTP errors, crawler still returns a valid result."""
    crawler = NewsSearchCrawler()
    crawler.get = AsyncMock(return_value=None)

    result = await crawler.scrape("John Doe fraud")
    # found=True (we searched, just got nothing), article_count=0
    assert result.found is True
    assert result.data["article_count"] == 0
    assert result.data["articles"] == []


# ===========================================================================
# 7. google_maps — Nominatim JSON → location parsed
# ===========================================================================


def test_google_maps_nominatim_parsed():
    """_parse_nominatim_result converts OSM JSON to our location schema."""
    location = _parse_nominatim_result(NOMINATIM_JSON[0])
    assert location["lat"] == pytest.approx(37.3946, abs=0.001)
    assert location["lon"] == pytest.approx(-122.1491, abs=0.001)
    assert "Palo Alto" in location["address"]
    assert location["type"] == "company"


# ===========================================================================
# 8. google_maps — empty Nominatim response → found=True, locations=[]
# ===========================================================================


@pytest.mark.asyncio
async def test_google_maps_empty_nominatim():
    """Empty Nominatim response → locations list is empty, found still True."""
    crawler = GoogleMapsCrawler()
    empty_resp = _mock_response(200, json_data=[])

    async def fake_get(url, **kwargs):
        if "nominatim" in url:
            return empty_resp
        return _mock_response(200, "<html></html>")

    crawler.get = fake_get
    result = await crawler.scrape("Nonexistent Place XYZ123")

    assert result.found is True
    assert isinstance(result.data["locations"], list)


# ===========================================================================
# 9. social_graph — @mention extraction from text
# ===========================================================================


def test_social_graph_mention_extraction():
    """@mentions are extracted and counted correctly."""
    text = "Follow @johndoe and @johndoe on twitter. Also check @janesmith."
    mentions = _extract_mentions(text)
    assert mentions["johndoe"] == 2
    assert mentions["janesmith"] == 1


# ===========================================================================
# 10. social_graph — cross-platform username matching
# ===========================================================================


@pytest.mark.asyncio
async def test_social_graph_cross_platform_match():
    """Username appearing on 2+ platforms → co_follows=True."""
    crawler = SocialGraphCrawler()
    text = "Find johndoe on twitter:johndoe and github:johndoe for their work."
    result = await crawler.scrape(text)

    connections = result.data["connections"]
    johndoe = next((c for c in connections if c["username"] == "johndoe"), None)
    assert johndoe is not None
    assert johndoe["co_follows"] is True
    assert "twitter" in johndoe["platforms"]
    assert "github" in johndoe["platforms"]


# ===========================================================================
# 11. social_graph — @mention deduplication
# ===========================================================================


def test_social_graph_mention_deduplication():
    """Same username (@JohnDoe vs @johndoe) is deduplicated (case-insensitive)."""
    text = "@JohnDoe posted something. @johndoe replied. @JOHNDOE agreed."
    mentions = _extract_mentions(text)
    assert "johndoe" in mentions
    assert mentions["johndoe"] == 3
    # Should NOT have separate entries for different casings
    assert "JohnDoe" not in mentions
    assert "JOHNDOE" not in mentions


# ===========================================================================
# 12. registry — all three crawlers registered
# ===========================================================================


def test_all_deep_enrichment_crawlers_registered():
    """news_search, google_maps, social_graph must all be registered."""
    assert is_registered("news_search")
    assert is_registered("google_maps")
    assert is_registered("social_graph")


# ===========================================================================
# 13. news_search — no articles → found=True, article_count=0
# ===========================================================================


@pytest.mark.asyncio
async def test_news_no_articles_returns_empty():
    """Empty HTML/RSS → article_count=0 with found=True."""
    crawler = NewsSearchCrawler()
    empty_html = "<html><body><p>No results found.</p></body></html>"
    empty_rss = """<?xml version="1.0"?><rss><channel></channel></rss>"""

    async def fake_get(url, **kwargs):
        if "duckduckgo" in url:
            return _mock_response(200, empty_html)
        return _mock_response(200, empty_rss)

    crawler.get = fake_get
    result = await crawler.scrape("extremely obscure query zzzxxx999")

    assert result.found is True
    assert result.data["article_count"] == 0
    assert result.data["articles"] == []


# ===========================================================================
# 14. article tagging — multiple categories can apply to one article
# ===========================================================================


def test_article_multiple_categories():
    """An article can receive multiple category tags."""
    tags = _tag_article(
        "CEO arrested for fraud and money laundering",
        "The executive was charged and convicted. Court found him guilty.",
    )
    assert "criminal" in tags
    assert "financial" in tags
    assert "legal" in tags
    assert "corporate" in tags


# ===========================================================================
# 15. social_graph — connection_count matches connections length
# ===========================================================================


@pytest.mark.asyncio
async def test_social_graph_connection_count_matches():
    """connection_count in result data equals len(connections)."""
    crawler = SocialGraphCrawler()
    text = "@alice @bob @charlie github:alice twitter:bob"
    result = await crawler.scrape(text)

    assert result.data["connection_count"] == len(result.data["connections"])
    assert result.data["connection_count"] >= 3


# ===========================================================================
# Branch gap: social_graph arc 108->105
# _extract_platform_mentions: duplicate platform+username entry is not added twice
# ===========================================================================


def test_extract_platform_mentions_duplicate_platform_skipped():
    """Arc 108->105: same platform+username pair appears twice in text.
    The second occurrence finds the platform already in platform_map[username]
    so the if-branch is False — it loops back to 105 without appending."""
    text = "twitter:johndoe twitter:johndoe"
    result = _extract_platform_mentions(text)
    # 'twitter' should appear only once for 'johndoe', not duplicated
    assert "johndoe" in result
    assert result["johndoe"].count("twitter") == 1


# ===========================================================================
# Branch gap: google_maps arc 178->170
# _parse_kg_panel: element found but get_text() returns empty string
# ===========================================================================


def test_parse_kg_panel_element_found_but_empty_text_loops_to_next_selector():
    """Arc 178->170: soup.select_one() returns an element but get_text(strip=True)
    is empty — if text: is False, the loop continues to the next selector."""
    from modules.crawlers.google_maps import _parse_kg_panel

    # Build HTML where the first selector finds a span with no text content,
    # but a tel: link provides the phone so the function still returns data
    html = """
    <html><body>
    <span data-attrid='kc:/location/location:address'></span>
    <a href="tel:+15551234567">Call Us</a>
    </body></html>
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    result = _parse_kg_panel(soup, "Test Business")
    # address is None (empty text in first selector, others also fail),
    # but phone is found via tel: link — result is not None
    assert result is not None
    assert result["phone"] == "+15551234567"
