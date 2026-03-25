"""
Phase 5 Expanded Crawlers — Test Suite

Groups:
  Task 1: Social Interest (threads, bluesky, spotify)
  Task 2: People Search (spokeo, familytreenow, radaris, clustrmaps)
  Task 3: State Courts (txcourts, fl_courts, ca_courts)
  Task 4: News & Mentions (google_news_rss, gdelt_mentions, bing_news)
  Task 5: Property & Vehicle (redfin_property, county_assessor_tx, county_assessor_fl, vin_decode_enhanced)
  Task 6: Professional & Financial (github_profile, stackoverflow_profile, sec_insider)
  Task 7: Interests Extractor meta-crawler
  Task 8: LinkedIn Enhancement + Coverage Tracking
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Task 1: Social Interest Crawlers ────────────────────────────────────────

@pytest.mark.asyncio
async def test_threads_profile_found():
    from modules.crawlers.threads_profile import ThreadsProfileCrawler
    crawler = ThreadsProfileCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": {
            "user": {
                "username": "john_doe",
                "biography": "tech lover",
                "edge_followed_by": {"count": 1200},
            }
        }
    }
    with patch.object(crawler, "get", return_value=mock_resp):
        result = await crawler.scrape("john_doe")
    assert result.found is True
    assert result.data["username"] == "john_doe"
    assert result.data["follower_count"] == 1200


@pytest.mark.asyncio
async def test_threads_profile_not_found():
    from modules.crawlers.threads_profile import ThreadsProfileCrawler
    crawler = ThreadsProfileCrawler()
    with patch.object(crawler, "get", return_value=None):
        result = await crawler.scrape("nobody_exists_xyzq")
    assert result.found is False


@pytest.mark.asyncio
async def test_bluesky_profile_found():
    from modules.crawlers.bluesky_profile import BlueskyProfileCrawler
    crawler = BlueskyProfileCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "displayName": "Jane Smith",
        "description": "writer",
        "followersCount": 850,
        "handle": "jane.bsky.social",
    }
    with patch.object(crawler, "get", return_value=mock_resp):
        result = await crawler.scrape("jane.bsky.social")
    assert result.found is True
    assert result.data["display_name"] == "Jane Smith"
    assert result.data["follower_count"] == 850


@pytest.mark.asyncio
async def test_bluesky_profile_not_found():
    from modules.crawlers.bluesky_profile import BlueskyProfileCrawler
    crawler = BlueskyProfileCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    with patch.object(crawler, "get", return_value=mock_resp):
        result = await crawler.scrape("doesnotexist.bsky.social")
    assert result.found is False


@pytest.mark.asyncio
async def test_spotify_public_found():
    from modules.crawlers.spotify_public import SpotifyPublicCrawler
    crawler = SpotifyPublicCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "users": {
            "items": [
                {"display_name": "John Doe", "id": "johndoe123", "type": "user"},
            ]
        }
    }
    with patch.object(crawler, "get", return_value=mock_resp):
        result = await crawler.scrape("John Doe")
    assert result.found is True
    assert len(result.data["users"]) == 1


@pytest.mark.asyncio
async def test_spotify_public_not_found():
    from modules.crawlers.spotify_public import SpotifyPublicCrawler
    crawler = SpotifyPublicCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"users": {"items": []}}
    with patch.object(crawler, "get", return_value=mock_resp):
        result = await crawler.scrape("xyzzznotaperson999")
    assert result.found is False


# ── Task 2: People Search Crawlers ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_spokeo_found():
    from modules.crawlers.spokeo import SpokeoCrawler
    crawler = SpokeoCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "solution": {
            "response": "<html><div class='name-age'>John Doe, 45</div><div class='address'>123 Main St, Dallas TX</div></html>",
            "status": 200,
        }
    }
    with patch.object(crawler, "post", return_value=mock_resp):
        result = await crawler.scrape("John Doe")
    assert result.found is True


@pytest.mark.asyncio
async def test_spokeo_not_found():
    from modules.crawlers.spokeo import SpokeoCrawler
    crawler = SpokeoCrawler()
    with patch.object(crawler, "post", return_value=None):
        result = await crawler.scrape("John Doe")
    assert result.found is False


@pytest.mark.asyncio
async def test_familytreenow_found():
    from modules.crawlers.familytreenow import FamilyTreeNowCrawler
    crawler = FamilyTreeNowCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><div class='card-block'><span class='name'>John Doe</span><span class='age'>45</span></div></html>"
    with patch.object(crawler, "get", return_value=mock_resp):
        result = await crawler.scrape("John Doe")
    assert result.found is True
    assert result.data["result_count"] >= 1


@pytest.mark.asyncio
async def test_familytreenow_not_found():
    from modules.crawlers.familytreenow import FamilyTreeNowCrawler
    crawler = FamilyTreeNowCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><p>No results found</p></html>"
    with patch.object(crawler, "get", return_value=mock_resp):
        result = await crawler.scrape("Zzznobody Fakename")
    assert result.found is False


@pytest.mark.asyncio
async def test_radaris_found():
    from modules.crawlers.radaris import RadarisCrawler
    crawler = RadarisCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><h1 class='profile-name'>John Doe</h1><div class='address'>Dallas, TX</div></html>"
    with patch.object(crawler, "get", return_value=mock_resp):
        result = await crawler.scrape("John Doe")
    assert result.found is True


@pytest.mark.asyncio
async def test_radaris_not_found():
    from modules.crawlers.radaris import RadarisCrawler
    crawler = RadarisCrawler()
    with patch.object(crawler, "get", return_value=None):
        result = await crawler.scrape("Zzznobody Fakename")
    assert result.found is False


@pytest.mark.asyncio
async def test_clustrmaps_found():
    from modules.crawlers.clustrmaps import ClustrMapsCrawler
    crawler = ClustrMapsCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><h1>John Doe</h1><div class='address-item'>123 Main St, Dallas TX 75201</div></html>"
    with patch.object(crawler, "get", return_value=mock_resp):
        result = await crawler.scrape("John Doe")
    assert result.found is True
    assert len(result.data["addresses"]) >= 1


@pytest.mark.asyncio
async def test_clustrmaps_not_found():
    from modules.crawlers.clustrmaps import ClustrMapsCrawler
    crawler = ClustrMapsCrawler()
    with patch.object(crawler, "get", return_value=None):
        result = await crawler.scrape("Zzznobody Fakename")
    assert result.found is False


# ── Task 3: State Court Crawlers ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_txcourts_found():
    from modules.crawlers.txcourts import TxCourtsCrawler
    crawler = TxCourtsCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><table class='results'><tr><td class='case-number'>2023-CV-001234</td><td>John Doe v. State</td></tr></table></html>"
    with patch.object(crawler, "get", return_value=mock_resp):
        result = await crawler.scrape("John Doe")
    assert result.found is True
    assert len(result.data["cases"]) >= 1
    assert "2023-CV-001234" in result.data["cases"][0]["case_number"]


@pytest.mark.asyncio
async def test_txcourts_not_found():
    from modules.crawlers.txcourts import TxCourtsCrawler
    crawler = TxCourtsCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><p>No cases found</p></html>"
    with patch.object(crawler, "get", return_value=mock_resp):
        result = await crawler.scrape("Zzznobody Fakename")
    assert result.found is False


@pytest.mark.asyncio
async def test_fl_courts_found():
    from modules.crawlers.fl_courts import FlCourtsCrawler
    crawler = FlCourtsCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><div class='case-result'><span class='case-number'>2023-CC-000123</span><span class='party'>John Doe</span></div></html>"
    with patch.object(crawler, "get", return_value=mock_resp):
        result = await crawler.scrape("John Doe")
    assert result.found is True
    assert len(result.data["cases"]) >= 1


@pytest.mark.asyncio
async def test_fl_courts_not_found():
    from modules.crawlers.fl_courts import FlCourtsCrawler
    crawler = FlCourtsCrawler()
    with patch.object(crawler, "get", return_value=None):
        result = await crawler.scrape("Zzznobody Fakename")
    assert result.found is False


@pytest.mark.asyncio
async def test_ca_courts_found():
    from modules.crawlers.ca_courts import CaCourtsCrawler
    crawler = CaCourtsCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><table id='caselist'><tr><td>23STCV00001</td><td>DOE, JOHN vs STATE</td><td>Civil</td></tr></table></html>"
    with patch.object(crawler, "get", return_value=mock_resp):
        result = await crawler.scrape("John Doe")
    assert result.found is True
    assert len(result.data["cases"]) >= 1


@pytest.mark.asyncio
async def test_ca_courts_not_found():
    from modules.crawlers.ca_courts import CaCourtsCrawler
    crawler = CaCourtsCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><p>No matching cases</p></html>"
    with patch.object(crawler, "get", return_value=mock_resp):
        result = await crawler.scrape("Zzznobody Fakename")
    assert result.found is False


# ── Task 4: News & Mentions Crawlers ────────────────────────────────────────

@pytest.mark.asyncio
async def test_google_news_rss_found():
    from modules.crawlers.google_news_rss import GoogleNewsRssCrawler
    crawler = GoogleNewsRssCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<item><title>John Doe Wins Award</title><link>https://example.com/1</link><pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate><source>Example News</source></item>
<item><title>John Doe Named CEO</title><link>https://example.com/2</link><pubDate>Tue, 02 Jan 2024 00:00:00 GMT</pubDate><source>Tech Times</source></item>
</channel></rss>"""
    with patch.object(crawler, "get", return_value=mock_resp):
        result = await crawler.scrape("John Doe")
    assert result.found is True
    assert len(result.data["articles"]) == 2
    assert result.data["articles"][0]["title"] == "John Doe Wins Award"


@pytest.mark.asyncio
async def test_google_news_rss_not_found():
    from modules.crawlers.google_news_rss import GoogleNewsRssCrawler
    crawler = GoogleNewsRssCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = '<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>'
    with patch.object(crawler, "get", return_value=mock_resp):
        result = await crawler.scrape("Zzznobody Fakename")
    assert result.found is False


@pytest.mark.asyncio
async def test_gdelt_mentions_found():
    from modules.crawlers.gdelt_mentions import GdeltMentionsCrawler
    crawler = GdeltMentionsCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "articles": [
            {"title": "John Doe in the News", "url": "https://example.com/1", "seendate": "20240101T000000Z", "domain": "example.com"},
            {"title": "Doe Foundation Donates", "url": "https://example.com/2", "seendate": "20240102T000000Z", "domain": "charity.org"},
        ]
    }
    with patch.object(crawler, "get", return_value=mock_resp):
        result = await crawler.scrape("John Doe")
    assert result.found is True
    assert len(result.data["articles"]) == 2


@pytest.mark.asyncio
async def test_gdelt_mentions_not_found():
    from modules.crawlers.gdelt_mentions import GdeltMentionsCrawler
    crawler = GdeltMentionsCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"articles": []}
    with patch.object(crawler, "get", return_value=mock_resp):
        result = await crawler.scrape("Zzznobody Fakename")
    assert result.found is False


@pytest.mark.asyncio
async def test_bing_news_found():
    from modules.crawlers.bing_news import BingNewsCrawler
    crawler = BingNewsCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<item><title>John Doe Launches Startup</title><link>https://bing.com/news/1</link><pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate></item>
</channel></rss>"""
    with patch.object(crawler, "get", return_value=mock_resp):
        result = await crawler.scrape("John Doe")
    assert result.found is True
    assert len(result.data["articles"]) == 1


@pytest.mark.asyncio
async def test_bing_news_not_found():
    from modules.crawlers.bing_news import BingNewsCrawler
    crawler = BingNewsCrawler()
    with patch.object(crawler, "get", return_value=None):
        result = await crawler.scrape("Zzznobody Fakename")
    assert result.found is False


# ── Task 5: Property & Vehicle Crawlers ─────────────────────────────────────

@pytest.mark.asyncio
async def test_redfin_property_found():
    from modules.crawlers.redfin_property import RedfinPropertyCrawler
    crawler = RedfinPropertyCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "payload": {
            "homes": [
                {
                    "address": {"streetAddress": "123 Main St", "city": "Dallas", "state": "TX", "zip": "75201"},
                    "price": 350000,
                    "beds": 3,
                    "baths": 2,
                }
            ]
        }
    }
    with patch.object(crawler, "get", return_value=mock_resp):
        result = await crawler.scrape("123 Main St Dallas TX")
    assert result.found is True
    assert result.data["properties"][0]["price"] == 350000


@pytest.mark.asyncio
async def test_redfin_property_not_found():
    from modules.crawlers.redfin_property import RedfinPropertyCrawler
    crawler = RedfinPropertyCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"payload": {"homes": []}}
    with patch.object(crawler, "get", return_value=mock_resp):
        result = await crawler.scrape("999 Nowhere St")
    assert result.found is False


@pytest.mark.asyncio
async def test_county_assessor_tx_found():
    from modules.crawlers.county_assessor_tx import CountyAssessorTxCrawler
    crawler = CountyAssessorTxCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><table class='results'><tr><td class='account'>1234567</td><td class='owner'>DOE JOHN</td><td class='appraised'>$450,000</td></tr></table></html>"
    with patch.object(crawler, "get", return_value=mock_resp):
        result = await crawler.scrape("123 Main St")
    assert result.found is True
    assert result.data["parcels"][0]["owner"] == "DOE JOHN"


@pytest.mark.asyncio
async def test_county_assessor_tx_not_found():
    from modules.crawlers.county_assessor_tx import CountyAssessorTxCrawler
    crawler = CountyAssessorTxCrawler()
    with patch.object(crawler, "get", return_value=None):
        result = await crawler.scrape("999 Nowhere St")
    assert result.found is False


@pytest.mark.asyncio
async def test_county_assessor_fl_found():
    from modules.crawlers.county_assessor_fl import CountyAssessorFlCrawler
    crawler = CountyAssessorFlCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><div class='parcel-result'><span class='parcel-id'>25-23-28-0000-00-001</span><span class='owner-name'>DOE, JOHN</span><span class='just-value'>$320,000</span></div></html>"
    with patch.object(crawler, "get", return_value=mock_resp):
        result = await crawler.scrape("123 Main St Orlando FL")
    assert result.found is True
    assert len(result.data["parcels"]) >= 1


@pytest.mark.asyncio
async def test_county_assessor_fl_not_found():
    from modules.crawlers.county_assessor_fl import CountyAssessorFlCrawler
    crawler = CountyAssessorFlCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><p>No parcels found</p></html>"
    with patch.object(crawler, "get", return_value=mock_resp):
        result = await crawler.scrape("999 Nowhere St")
    assert result.found is False


@pytest.mark.asyncio
async def test_vin_decode_enhanced_found():
    from modules.crawlers.vin_decode_enhanced import VinDecodeEnhancedCrawler
    crawler = VinDecodeEnhancedCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "Results": [
            {
                "Make": "TOYOTA",
                "Model": "CAMRY",
                "ModelYear": "2020",
                "BodyClass": "Sedan",
                "DriveType": "FWD",
                "EngineCylinders": "4",
                "FuelTypePrimary": "Gasoline",
                "GVWR": "4015 lb",
                "PlantCountry": "UNITED STATES (USA)",
                "ErrorCode": "0",
            }
        ]
    }
    with patch.object(crawler, "get", return_value=mock_resp):
        result = await crawler.scrape("4T1BF1FK4LU123456")
    assert result.found is True
    assert result.data["make"] == "TOYOTA"
    assert result.data["model"] == "CAMRY"


@pytest.mark.asyncio
async def test_vin_decode_enhanced_not_found():
    from modules.crawlers.vin_decode_enhanced import VinDecodeEnhancedCrawler
    crawler = VinDecodeEnhancedCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "Results": [{"Make": "", "Model": "", "ModelYear": "", "ErrorCode": "8"}]
    }
    with patch.object(crawler, "get", return_value=mock_resp):
        result = await crawler.scrape("00000000000000000")
    assert result.found is False


# ── Task 6: Professional & Financial Crawlers ────────────────────────────────

@pytest.mark.asyncio
async def test_github_profile_found():
    from modules.crawlers.github_profile import GitHubProfileCrawler
    crawler = GitHubProfileCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "total_count": 1,
        "items": [
            {
                "login": "johndoe",
                "name": "John Doe",
                "public_repos": 42,
                "followers": 310,
                "html_url": "https://github.com/johndoe",
            }
        ],
    }
    with patch.object(crawler, "get", return_value=mock_resp):
        result = await crawler.scrape("John Doe")
    assert result.found is True
    assert result.data["profiles"][0]["login"] == "johndoe"
    assert result.data["profiles"][0]["public_repos"] == 42


@pytest.mark.asyncio
async def test_github_profile_not_found():
    from modules.crawlers.github_profile import GitHubProfileCrawler
    crawler = GitHubProfileCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"total_count": 0, "items": []}
    with patch.object(crawler, "get", return_value=mock_resp):
        result = await crawler.scrape("Zzznobody Fakename")
    assert result.found is False


@pytest.mark.asyncio
async def test_stackoverflow_profile_found():
    from modules.crawlers.stackoverflow_profile import StackOverflowProfileCrawler
    crawler = StackOverflowProfileCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "items": [
            {
                "user_id": 12345,
                "display_name": "John Doe",
                "reputation": 5430,
                "badge_counts": {"gold": 2, "silver": 15, "bronze": 40},
                "link": "https://stackoverflow.com/users/12345/john-doe",
            }
        ]
    }
    with patch.object(crawler, "get", return_value=mock_resp):
        result = await crawler.scrape("John Doe")
    assert result.found is True
    assert result.data["profiles"][0]["reputation"] == 5430


@pytest.mark.asyncio
async def test_stackoverflow_profile_not_found():
    from modules.crawlers.stackoverflow_profile import StackOverflowProfileCrawler
    crawler = StackOverflowProfileCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"items": []}
    with patch.object(crawler, "get", return_value=mock_resp):
        result = await crawler.scrape("Zzznobody Fakename")
    assert result.found is False


@pytest.mark.asyncio
async def test_sec_insider_found():
    from modules.crawlers.sec_insider import SecInsiderCrawler
    crawler = SecInsiderCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "hits": {
            "hits": [
                {
                    "_source": {
                        "period_of_report": "2023-01-15",
                        "entity_name": "ACME Corp",
                        "file_date": "2023-01-20",
                        "form_type": "4",
                    }
                }
            ],
            "total": {"value": 1},
        }
    }
    with patch.object(crawler, "get", return_value=mock_resp):
        result = await crawler.scrape("John Doe")
    assert result.found is True
    assert result.data["filings"][0]["entity_name"] == "ACME Corp"


@pytest.mark.asyncio
async def test_sec_insider_not_found():
    from modules.crawlers.sec_insider import SecInsiderCrawler
    crawler = SecInsiderCrawler()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"hits": {"hits": [], "total": {"value": 0}}}
    with patch.object(crawler, "get", return_value=mock_resp):
        result = await crawler.scrape("Zzznobody Fakename")
    assert result.found is False


# ── Task 7: Interests Extractor Meta-Crawler ─────────────────────────────────

@pytest.mark.asyncio
async def test_interests_extractor_extracts_subreddits():
    from modules.crawlers.interests_extractor import InterestsExtractorCrawler
    crawler = InterestsExtractorCrawler()
    mock_session = MagicMock()

    reddit_job = MagicMock()
    reddit_job.meta = {
        "platform": "reddit",
        "result": {
            "recent_posts": [
                {"subreddit": "personalfinance"},
                {"subreddit": "investing"},
                {"subreddit": "personalfinance"},  # duplicate — should be deduped
            ]
        },
    }
    threads_job = MagicMock()
    threads_job.meta = {
        "platform": "threads_profile",
        "result": {"bio": "crypto and DeFi enthusiast"},
    }

    mock_session.execute = AsyncMock(
        return_value=MagicMock(
            scalars=MagicMock(
                return_value=MagicMock(all=MagicMock(return_value=[reddit_job, threads_job]))
            )
        )
    )

    result = await crawler.scrape("some-person-uuid", session=mock_session)
    assert result.found is True
    assert "personalfinance" in result.data["interests"]
    assert "investing" in result.data["interests"]
    # Deduplicated — personalfinance appears once
    assert result.data["interests"].count("personalfinance") == 1


@pytest.mark.asyncio
async def test_interests_extractor_no_jobs():
    from modules.crawlers.interests_extractor import InterestsExtractorCrawler
    crawler = InterestsExtractorCrawler()
    mock_session = MagicMock()
    mock_session.execute = AsyncMock(
        return_value=MagicMock(
            scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        )
    )
    result = await crawler.scrape("some-person-uuid", session=mock_session)
    assert result.found is False


# ── Task 8: LinkedIn Enhancement + Coverage Tracking ─────────────────────────

@pytest.mark.asyncio
async def test_linkedin_extract_skills():
    from modules.crawlers.linkedin import LinkedInCrawler
    crawler = LinkedInCrawler()

    mock_page = AsyncMock()
    mock_page.url = "https://www.linkedin.com/in/johndoe/"
    mock_page.title = AsyncMock(return_value="John Doe | LinkedIn")
    mock_page.content = AsyncMock(return_value="<html>John Doe profile</html>")
    mock_page.__aenter__ = AsyncMock(return_value=mock_page)
    mock_page.__aexit__ = AsyncMock(return_value=False)

    skill_el_1 = AsyncMock()
    skill_el_1.inner_text = AsyncMock(return_value="Python")
    skill_el_2 = AsyncMock()
    skill_el_2.inner_text = AsyncMock(return_value="Machine Learning")

    mock_page.query_selector = AsyncMock(return_value=None)
    mock_page.query_selector_all = AsyncMock(return_value=[skill_el_1, skill_el_2])

    with patch.object(crawler, "page", return_value=mock_page):
        data = await crawler._extract(mock_page, "johndoe")

    assert "skills" in data
    assert "Python" in data["skills"]


@pytest.mark.asyncio
async def test_coverage_tracking_updates_person_meta():
    from modules.pipeline.enrichment_orchestrator import EnrichmentOrchestrator
    import uuid

    orchestrator = EnrichmentOrchestrator()
    person_id = str(uuid.uuid4())

    mock_session = AsyncMock()

    mock_person = MagicMock()
    mock_person.meta = {}
    mock_session.get = AsyncMock(return_value=mock_person)

    with patch.object(orchestrator, "_run_financial_aml", return_value=None), \
         patch.object(orchestrator, "_run_marketing_tags", return_value=None), \
         patch.object(orchestrator, "_run_deduplication", return_value=None), \
         patch.object(orchestrator, "_run_burner", return_value=None), \
         patch.object(orchestrator, "_run_relationship_score", return_value=None), \
         patch.object(orchestrator, "_update_coverage", return_value=None) as mock_coverage:
        report = await orchestrator.enrich_person(person_id, mock_session)

    mock_coverage.assert_called_once_with(person_id, mock_session)
    assert report.person_id == person_id
