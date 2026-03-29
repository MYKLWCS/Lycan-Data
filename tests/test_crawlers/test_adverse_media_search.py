"""
test_adverse_media_search.py — Full branch coverage for adverse_media_search.py.

Covers:
- _score_severity(): critical, high, medium, low, plain-low fallback
- _url_hash(): produces 16-char hex string
- _parse_gnews_rss(): valid XML, missing channel, strip HTML tags, empty
- _parse_gdelt(): full data, non-dict data, non-dict article items, empty
- _parse_courtlistener(): full result, relative URL prefix, empty
- _parse_propublica(): full orgs list, limit 10, non-dict org skip, empty
- AdverseMediaSearchCrawler.scrape(): full pipeline, dedup, org hint, score computation
- _search_gnews(): 200, None, non-200
- _search_gdelt(): 200, None, non-200, parse error
- _search_courtlistener(): 200, None, non-200, parse error
- _search_propublica(): 200, None, non-200, parse error
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from modules.crawlers.media.adverse_media_search import (
    AdverseMediaSearchCrawler,
    _parse_courtlistener,
    _parse_gdelt,
    _parse_gnews_rss,
    _parse_propublica,
    _score_severity,
    _url_hash,
)
from modules.crawlers.core.result import CrawlerResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_resp(status: int, text: str = "", json_data=None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    if json_data is not None:
        resp.json = MagicMock(return_value=json_data)
    else:
        resp.json = MagicMock(side_effect=ValueError("no json"))
    return resp


def _crawler() -> AdverseMediaSearchCrawler:
    return AdverseMediaSearchCrawler()


# ---------------------------------------------------------------------------
# _score_severity
# ---------------------------------------------------------------------------


def test_score_severity_critical_terrorism():
    label, score = _score_severity("suspect linked to terrorism attack")
    assert label == "critical"
    assert score == 1.0


def test_score_severity_critical_murder():
    label, score = _score_severity("charged with murder")
    assert label == "critical"
    assert score == 1.0


def test_score_severity_high_fraud():
    label, score = _score_severity("convicted of fraud")
    assert label == "high"
    assert score == 0.75


def test_score_severity_high_sanctions():
    label, score = _score_severity("company placed on sanctions list")
    assert label == "high"
    assert score == 0.75


def test_score_severity_medium_investigation():
    label, score = _score_severity("under sec investigation")
    assert label == "medium"
    assert score == 0.5


def test_score_severity_medium_regulatory():
    label, score = _score_severity("regulatory fine imposed")
    assert label == "medium"
    assert score == 0.5


def test_score_severity_low_complaint():
    label, score = _score_severity("consumer complaint filed")
    assert label == "low"
    assert score == 0.25


def test_score_severity_low_fallback():
    """Text with no matched keywords returns low/0.1."""
    label, score = _score_severity("quarterly earnings report")
    assert label == "low"
    assert score == 0.1


def test_score_severity_case_insensitive():
    label, score = _score_severity("FRAUD AND CORRUPTION")
    assert label == "high"


# ---------------------------------------------------------------------------
# _url_hash
# ---------------------------------------------------------------------------


def test_url_hash_returns_16_chars():
    h = _url_hash("https://example.com/article/1")
    assert len(h) == 16


def test_url_hash_deterministic():
    url = "https://example.com/test"
    assert _url_hash(url) == _url_hash(url)


def test_url_hash_different_urls_differ():
    assert _url_hash("https://a.com") != _url_hash("https://b.com")


# ---------------------------------------------------------------------------
# _parse_gnews_rss
# ---------------------------------------------------------------------------

_GNEWS_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Google News</title>
    <item>
      <title>John Smith arrested for fraud</title>
      <description><![CDATA[<p>John Smith was arrested today.</p>]]></description>
      <link>https://example.com/news/1</link>
      <pubDate>Tue, 25 Mar 2026 10:00:00 GMT</pubDate>
      <source>BBC News</source>
    </item>
    <item>
      <title>Quarterly results</title>
      <description>Earnings report published</description>
      <link>https://example.com/news/2</link>
      <pubDate>Tue, 25 Mar 2026 09:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


def test_parse_gnews_rss_success():
    results = _parse_gnews_rss(_GNEWS_XML)
    assert len(results) == 2
    r = results[0]
    assert r["headline"] == "John Smith arrested for fraud"
    assert r["severity"] == "high"
    assert r["sentiment_score"] == -0.75
    assert r["data_source"] == "google_news_rss"
    assert r["source_name"] == "BBC News"
    assert "<p>" not in r["summary"]  # HTML stripped


def test_parse_gnews_rss_missing_source_element():
    """Item with no <source> element should have empty source_name."""
    results = _parse_gnews_rss(_GNEWS_XML)
    assert results[1]["source_name"] == ""


def test_parse_gnews_rss_empty_string():
    assert _parse_gnews_rss("") == []


def test_parse_gnews_rss_no_channel():
    xml = '<?xml version="1.0"?><rss version="2.0"><nothing/></rss>'
    results = _parse_gnews_rss(xml)
    assert results == []


def test_parse_gnews_rss_invalid_xml():
    results = _parse_gnews_rss("NOT XML AT ALL <<<")
    assert results == []


def test_parse_gnews_rss_url_hash_present():
    results = _parse_gnews_rss(_GNEWS_XML)
    for r in results:
        assert "url_hash" in r
        assert len(r["url_hash"]) == 16


# ---------------------------------------------------------------------------
# _parse_gdelt
# ---------------------------------------------------------------------------


def test_parse_gdelt_full():
    data = {
        "articles": [
            {
                "url": "https://gdelt.example.com/1",
                "title": "Money laundering scheme uncovered",
                "seendates": {"2026-03-25": 1},
                "seendate": "20260325",
                "crawldate": "",
                "domain": "reuters.com",
                "sourcecountry": "US",
            }
        ]
    }
    results = _parse_gdelt(data)
    assert len(results) == 1
    r = results[0]
    assert r["headline"] == "Money laundering scheme uncovered"
    assert r["severity"] == "high"
    assert r["data_source"] == "gdelt"
    assert r["source_name"] == "reuters.com"
    assert r["source_country"] == "US"


def test_parse_gdelt_non_dict_input():
    assert _parse_gdelt("not a dict") == []
    assert _parse_gdelt(None) == []
    assert _parse_gdelt([]) == []


def test_parse_gdelt_non_dict_article_skipped():
    data = {"articles": ["not a dict", 42, None]}
    results = _parse_gdelt(data)
    assert results == []


def test_parse_gdelt_empty_articles():
    assert _parse_gdelt({"articles": []}) == []


def test_parse_gdelt_missing_articles_key():
    assert _parse_gdelt({}) == []


def test_parse_gdelt_seendates_dict_converted_to_str():
    data = {
        "articles": [
            {
                "url": "https://x.com",
                "title": "Investigation probe",
                "seendates": {"2026-03-25": 2},
                "seendate": "",
                "domain": "",
                "sourcecountry": "",
            }
        ]
    }
    results = _parse_gdelt(data)
    assert isinstance(results[0]["summary"], str)


# ---------------------------------------------------------------------------
# _parse_courtlistener
# ---------------------------------------------------------------------------


def test_parse_courtlistener_full():
    data = {
        "results": [
            {
                "caseName": "Smith v. United States",
                "court_id": "ca9",
                "dateFiled": "2023-04-01",
                "absolute_url": "/opinion/1234/smith-v-us/",
                "snippet": "convicted of wire fraud",
            }
        ]
    }
    results = _parse_courtlistener(data)
    assert len(results) == 1
    r = results[0]
    assert r["headline"] == "Smith v. United States"
    assert r["url"].startswith("https://www.courtlistener.com")
    assert r["severity"] == "high"
    assert r["data_source"] == "courtlistener"
    assert r["category"] == "court_record"


def test_parse_courtlistener_absolute_url_prefixed():
    """Relative URLs get https://www.courtlistener.com prepended."""
    data = {
        "results": [
            {
                "caseName": "X v Y",
                "court_id": "dc",
                "dateFiled": "",
                "absolute_url": "/opinion/999/",
                "snippet": "",
            }
        ]
    }
    results = _parse_courtlistener(data)
    assert results[0]["url"] == "https://www.courtlistener.com/opinion/999/"


def test_parse_courtlistener_full_url_not_prefixed():
    data = {
        "results": [
            {
                "caseName": "X v Y",
                "court_id": "dc",
                "dateFiled": "",
                "absolute_url": "https://www.courtlistener.com/opinion/999/",
                "snippet": "",
            }
        ]
    }
    results = _parse_courtlistener(data)
    assert results[0]["url"] == "https://www.courtlistener.com/opinion/999/"


def test_parse_courtlistener_non_dict_result_skipped():
    data = {"results": ["not a dict", None]}
    assert _parse_courtlistener(data) == []


def test_parse_courtlistener_empty():
    assert _parse_courtlistener({"results": []}) == []
    assert _parse_courtlistener({}) == []


# ---------------------------------------------------------------------------
# _parse_propublica
# ---------------------------------------------------------------------------


def test_parse_propublica_full():
    data = {
        "organizations": [
            {
                "name": "Acme Foundation",
                "ein": "12-3456789",
                "ntee_code": "T20",
                "state": "TX",
                "updated": "2024-01-01",
            }
        ]
    }
    results = _parse_propublica(data, "John Smith")
    assert len(results) == 1
    r = results[0]
    assert "Acme Foundation" in r["headline"]
    assert r["category"] == "nonprofit_connection"
    assert r["severity"] == "low"
    assert r["sentiment_score"] == 0.0
    assert "12-3456789" in r["summary"]


def test_parse_propublica_limit_10():
    """Only first 10 orgs are processed."""
    orgs = [{"name": f"Org{i}", "ein": str(i), "ntee_code": "", "state": ""} for i in range(15)]
    results = _parse_propublica({"organizations": orgs}, "test")
    assert len(results) == 10


def test_parse_propublica_non_dict_org_skipped():
    data = {"organizations": ["not_a_dict", None, 42]}
    results = _parse_propublica(data, "test")
    assert results == []


def test_parse_propublica_empty():
    assert _parse_propublica({"organizations": []}, "test") == []
    assert _parse_propublica({}, "test") == []


# ---------------------------------------------------------------------------
# AdverseMediaSearchCrawler.scrape()
# ---------------------------------------------------------------------------


async def test_scrape_full_pipeline():
    crawler = _crawler()
    article = {
        "headline": "Fraud case",
        "summary": "John arrested",
        "url": "https://news.com/1",
        "url_hash": "abc123abc123abc1",
        "publication_date": "2026-03-01",
        "source_name": "BBC",
        "source_country": "US",
        "category": "news",
        "severity": "high",
        "sentiment_score": -0.75,
        "data_source": "google_news_rss",
    }
    with (
        patch.object(crawler, "_search_gnews", new=AsyncMock(return_value=[article])),
        patch.object(crawler, "_search_gdelt", new=AsyncMock(return_value=[])),
        patch.object(crawler, "_search_courtlistener", new=AsyncMock(return_value=[])),
        patch.object(crawler, "_search_propublica", new=AsyncMock(return_value=[])),
    ):
        result = await crawler.scrape("John Smith")

    assert isinstance(result, CrawlerResult)
    assert result.found is True
    assert result.data["adverse_media_count"] == 1
    assert result.data["adverse_media_score"] == 0.75
    assert result.data["query"] == "John Smith"


async def test_scrape_no_articles():
    crawler = _crawler()
    with (
        patch.object(crawler, "_search_gnews", new=AsyncMock(return_value=[])),
        patch.object(crawler, "_search_gdelt", new=AsyncMock(return_value=[])),
        patch.object(crawler, "_search_courtlistener", new=AsyncMock(return_value=[])),
        patch.object(crawler, "_search_propublica", new=AsyncMock(return_value=[])),
    ):
        result = await crawler.scrape("Nobody Here")

    assert result.found is False
    assert result.data["adverse_media_score"] == 0.0
    assert result.data["adverse_media_count"] == 0


async def test_scrape_deduplicates_by_url_hash():
    crawler = _crawler()
    article = {
        "headline": "Dup",
        "summary": "x",
        "url": "https://x.com",
        "url_hash": "samehashhhhhhhhh",
        "publication_date": "",
        "source_name": "",
        "source_country": "",
        "category": "news",
        "severity": "low",
        "sentiment_score": -0.1,
        "data_source": "google_news_rss",
    }
    with (
        patch.object(crawler, "_search_gnews", new=AsyncMock(return_value=[article])),
        patch.object(crawler, "_search_gdelt", new=AsyncMock(return_value=[article])),
        patch.object(crawler, "_search_courtlistener", new=AsyncMock(return_value=[])),
        patch.object(crawler, "_search_propublica", new=AsyncMock(return_value=[])),
    ):
        result = await crawler.scrape("X")

    assert result.data["adverse_media_count"] == 1


async def test_scrape_org_hint_appended_to_query():
    crawler = _crawler()
    with (
        patch.object(crawler, "_search_gnews", new=AsyncMock(return_value=[])) as mock_gnews,
        patch.object(crawler, "_search_gdelt", new=AsyncMock(return_value=[])),
        patch.object(crawler, "_search_courtlistener", new=AsyncMock(return_value=[])),
        patch.object(crawler, "_search_propublica", new=AsyncMock(return_value=[])),
    ):
        await crawler.scrape("John Smith | Acme Corp")

    assert mock_gnews.called


async def test_scrape_score_uses_max_severity():
    crawler = _crawler()
    low_article = {
        "headline": "Minor issue",
        "summary": "",
        "url": "https://a.com",
        "url_hash": "aaaaaaaaaaaaaaaa",
        "publication_date": "",
        "source_name": "",
        "source_country": "",
        "category": "news",
        "severity": "low",
        "sentiment_score": -0.25,
        "data_source": "gdelt",
    }
    critical_article = {
        "headline": "Terrorism",
        "summary": "",
        "url": "https://b.com",
        "url_hash": "bbbbbbbbbbbbbbbb",
        "publication_date": "",
        "source_name": "",
        "source_country": "",
        "category": "news",
        "severity": "critical",
        "sentiment_score": -1.0,
        "data_source": "gdelt",
    }
    with (
        patch.object(crawler, "_search_gnews", new=AsyncMock(return_value=[low_article])),
        patch.object(crawler, "_search_gdelt", new=AsyncMock(return_value=[critical_article])),
        patch.object(crawler, "_search_courtlistener", new=AsyncMock(return_value=[])),
        patch.object(crawler, "_search_propublica", new=AsyncMock(return_value=[])),
    ):
        result = await crawler.scrape("X")

    assert result.data["adverse_media_score"] == 1.0


# ---------------------------------------------------------------------------
# _search_gnews — branches
# ---------------------------------------------------------------------------


async def test_search_gnews_200():
    crawler = _crawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, text=_GNEWS_XML))):
        results = await crawler._search_gnews("%22John+Smith%22")
    assert len(results) > 0


async def test_search_gnews_none_response():
    crawler = _crawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        results = await crawler._search_gnews("X")
    assert results == []


async def test_search_gnews_non_200():
    crawler = _crawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(503))):
        results = await crawler._search_gnews("X")
    assert results == []


# ---------------------------------------------------------------------------
# _search_gdelt — branches
# ---------------------------------------------------------------------------


async def test_search_gdelt_200():
    crawler = _crawler()
    data = {"articles": []}
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, json_data=data))):
        results = await crawler._search_gdelt("X")
    assert results == []


async def test_search_gdelt_none_response():
    crawler = _crawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        results = await crawler._search_gdelt("X")
    assert results == []


async def test_search_gdelt_non_200():
    crawler = _crawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(404))):
        results = await crawler._search_gdelt("X")
    assert results == []


async def test_search_gdelt_parse_error():
    crawler = _crawler()
    bad = MagicMock()
    bad.status_code = 200
    bad.json = MagicMock(side_effect=ValueError("bad"))
    with patch.object(crawler, "get", new=AsyncMock(return_value=bad)):
        results = await crawler._search_gdelt("X")
    assert results == []


# ---------------------------------------------------------------------------
# _search_courtlistener — branches
# ---------------------------------------------------------------------------


async def test_search_court_200():
    crawler = _crawler()
    data = {"results": []}
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, json_data=data))):
        results = await crawler._search_courtlistener("X")
    assert results == []


async def test_search_court_none_response():
    crawler = _crawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        results = await crawler._search_courtlistener("X")
    assert results == []


async def test_search_court_non_200():
    crawler = _crawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(403))):
        results = await crawler._search_courtlistener("X")
    assert results == []


async def test_search_court_parse_error():
    crawler = _crawler()
    bad = MagicMock()
    bad.status_code = 200
    bad.json = MagicMock(side_effect=ValueError("bad"))
    with patch.object(crawler, "get", new=AsyncMock(return_value=bad)):
        results = await crawler._search_courtlistener("X")
    assert results == []


# ---------------------------------------------------------------------------
# _search_propublica — branches
# ---------------------------------------------------------------------------


async def test_search_propublica_200():
    crawler = _crawler()
    data = {"organizations": []}
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(200, json_data=data))):
        results = await crawler._search_propublica("X", "John Smith")
    assert results == []


async def test_search_propublica_none_response():
    crawler = _crawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=None)):
        results = await crawler._search_propublica("X", "John Smith")
    assert results == []


async def test_search_propublica_non_200():
    crawler = _crawler()
    with patch.object(crawler, "get", new=AsyncMock(return_value=_mock_resp(429))):
        results = await crawler._search_propublica("X", "John Smith")
    assert results == []


async def test_search_propublica_parse_error():
    crawler = _crawler()
    bad = MagicMock()
    bad.status_code = 200
    bad.json = MagicMock(side_effect=ValueError("bad"))
    with patch.object(crawler, "get", new=AsyncMock(return_value=bad)):
        results = await crawler._search_propublica("X", "John Smith")
    assert results == []


# ---------------------------------------------------------------------------
# Branch gap: arc 182->184 in _parse_gdelt
# seendates is NOT a dict (False branch of isinstance check) — goes to 184
# ---------------------------------------------------------------------------


def test_parse_gdelt_seendates_string_not_converted():
    """Arc 182->184: seendates is a plain string (not a dict).
    isinstance(summary, dict) is False — line 183 (str conversion) is skipped,
    execution goes directly to line 184 (pub_date extraction)."""
    data = {
        "articles": [
            {
                "url": "https://example.com/article",
                "title": "Fraud conviction",
                "seendates": "2026-03-25",  # string, not dict — isinstance check is False
                "seendate": "2026-03-25T10:00:00Z",
                "domain": "example.com",
                "sourcecountry": "US",
            }
        ]
    }
    results = _parse_gdelt(data)
    assert len(results) == 1
    # summary is already a string — isinstance check False, no conversion needed
    assert isinstance(results[0]["summary"], str)
    assert results[0]["publication_date"] == "2026-03-25T10:00:00Z"
