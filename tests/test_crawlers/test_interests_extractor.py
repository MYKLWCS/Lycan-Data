"""
interests_extractor crawler coverage tests.

Targets lines not yet exercised:
  55-56: no session kwarg → no_session error
  102-104: followed_topics extraction
  108-110: liked_pages extraction
  113: no interests found → found=False
  118-124: interests found → found=True
  139-140: BehaviouralProfile is None → new profile created
  149: flush+commit path
  153-155: flush raises → rollback
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import modules.crawlers.interests_extractor  # noqa: F401 — trigger @register
from modules.crawlers.interests_extractor import InterestsExtractorCrawler


def _make_session(jobs=None, profile=None):
    session = AsyncMock()

    # execute() returns jobs on first call, profile on second
    call_count = [0]

    async def fake_execute(stmt):
        c = call_count[0]
        call_count[0] += 1
        r = MagicMock()
        if c == 0:
            # CrawlJob query
            r.scalars.return_value.all.return_value = jobs or []
        else:
            # BehaviouralProfile query
            r.scalar_one_or_none.return_value = profile
        return r

    session.execute = fake_execute
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


def _make_job(platform="reddit", result_data=None):
    job = MagicMock()
    job.meta = {"platform": platform, "result": result_data or {}}
    return job


# ===========================================================================
# lines 55-56: no session kwarg → no_session error
# ===========================================================================


class TestNoSession:
    @pytest.mark.asyncio
    async def test_scrape_no_session_returns_error(self):
        crawler = InterestsExtractorCrawler()
        result = await crawler.scrape("some-identifier")
        assert result.data.get("error") == "no_session"
        assert result.found is False


# ===========================================================================
# lines 102-104: followed_topics; lines 108-110: liked_pages
# ===========================================================================


class TestFollowedTopicsAndLikedPages:
    @pytest.mark.asyncio
    async def test_followed_topics_extracted(self):
        """followed_topics list → interest items added (lines 101-104)."""
        job = _make_job(platform="threads", result_data={"followed_topics": ["fitness", "gaming"]})
        session = _make_session(jobs=[job])

        crawler = InterestsExtractorCrawler()
        result = await crawler.scrape("00000000-0000-0000-0000-000000000001", session=session)
        assert result.found is True
        assert "fitness" in result.data["interests"]
        assert "gaming" in result.data["interests"]

    @pytest.mark.asyncio
    async def test_liked_pages_extracted(self):
        """liked_pages list → interest items added (lines 107-110)."""
        job = _make_job(platform="facebook", result_data={"liked_pages": ["Travel", "Cooking"]})
        session = _make_session(jobs=[job])

        crawler = InterestsExtractorCrawler()
        result = await crawler.scrape("00000000-0000-0000-0000-000000000001", session=session)
        assert result.found is True
        assert "travel" in result.data["interests"]
        assert "cooking" in result.data["interests"]


# ===========================================================================
# line 113: no interests extracted → found=False
# ===========================================================================


class TestNoInterestsFound:
    @pytest.mark.asyncio
    async def test_jobs_with_no_interests_returns_not_found(self):
        """All jobs have empty/no signals → interests=[] → found=False (line 113)."""
        job = _make_job(platform="unknown", result_data={})
        session = _make_session(jobs=[job])

        crawler = InterestsExtractorCrawler()
        result = await crawler.scrape("00000000-0000-0000-0000-000000000001", session=session)
        assert result.found is False


# ===========================================================================
# lines 139-140: new BehaviouralProfile created
# ===========================================================================


class TestPersistNewProfile:
    @pytest.mark.asyncio
    async def test_persist_creates_new_profile(self):
        """No existing profile → new BehaviouralProfile added (lines 138-140)."""
        job = _make_job(
            platform="reddit", result_data={"recent_posts": [{"subreddit": "investing"}]}
        )
        session = _make_session(jobs=[job], profile=None)  # profile=None → new row

        crawler = InterestsExtractorCrawler()
        result = await crawler.scrape("00000000-0000-0000-0000-000000000001", session=session)
        assert result.found is True
        assert session.add.called


# ===========================================================================
# existing profile merges interests (lines 141-145)
# ===========================================================================


class TestPersistExistingProfile:
    @pytest.mark.asyncio
    async def test_persist_merges_existing_interests(self):
        """Existing profile → merges old + new interests (lines 141-145)."""
        job = _make_job(platform="reddit", result_data={"recent_posts": [{"subreddit": "crypto"}]})

        existing_profile = MagicMock()
        existing_profile.interests = ["fitness"]
        session = _make_session(jobs=[job], profile=existing_profile)

        crawler = InterestsExtractorCrawler()
        result = await crawler.scrape("00000000-0000-0000-0000-000000000001", session=session)
        assert result.found is True
        # "crypto" should have been merged in
        assert "crypto" in existing_profile.interests


# ===========================================================================
# lines 150-155: flush raises → rollback
# ===========================================================================


class TestPersistFlushFailure:
    @pytest.mark.asyncio
    async def test_persist_flush_failure_rollback(self):
        """flush() raises → warning logged + rollback attempted (lines 150-155)."""
        job = _make_job(platform="reddit", result_data={"recent_posts": [{"subreddit": "gaming"}]})
        session = _make_session(jobs=[job], profile=None)
        session.flush = AsyncMock(side_effect=RuntimeError("db error"))

        crawler = InterestsExtractorCrawler()
        # Should not raise
        result = await crawler.scrape("00000000-0000-0000-0000-000000000001", session=session)
        assert result.found is True  # Returns True before persist fails
        session.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_persist_rollback_itself_raises(self):
        """rollback also fails → second exception swallowed (line 154)."""
        job = _make_job(platform="reddit", result_data={"recent_posts": [{"subreddit": "gaming"}]})
        session = _make_session(jobs=[job], profile=None)
        session.flush = AsyncMock(side_effect=RuntimeError("db error"))
        session.rollback = AsyncMock(side_effect=RuntimeError("rollback also fails"))

        crawler = InterestsExtractorCrawler()
        # Should not raise despite double failure
        result = await crawler.scrape("00000000-0000-0000-0000-000000000001", session=session)
        assert result.found is True


# ===========================================================================
# Branch gap: arc 112->110 — bio keyword already in interests (skip duplicate)
# Arc 126->124 — followed_topic already in interests or empty (False branch)
# Arc 132->130 — liked_page already in interests or empty (False branch)
# ===========================================================================


class TestInterestsDuplicateAndEmptyBranches:
    @pytest.mark.asyncio
    async def test_bio_keyword_already_in_interests_skipped(self):
        """Arc 112->110: a bio keyword already present in interests list is not appended again.
        The if-condition `keyword not in interests` is False — loops back to 110."""
        from modules.crawlers.interests_extractor import _BIO_INTEREST_KEYWORDS

        # First add a keyword via subreddit, then the bio also mentions it
        first_keyword = _BIO_INTEREST_KEYWORDS[0]
        job = _make_job(
            platform="reddit",
            result_data={
                "recent_posts": [{"subreddit": first_keyword}],
                "bio": first_keyword,  # same keyword appears in bio — duplicate
            },
        )
        session = _make_session(jobs=[job])
        crawler = InterestsExtractorCrawler()
        result = await crawler.scrape("00000000-0000-0000-0000-000000000002", session=session)
        assert result.found is True
        # Keyword appears exactly once despite being added via two paths
        assert result.data["interests"].count(first_keyword) == 1

    @pytest.mark.asyncio
    async def test_followed_topic_already_in_interests_not_duplicated(self):
        """Arc 126->124: a followed_topic already present in interests is skipped.
        The `if t and t not in interests:` condition is False — loops back to line 124."""
        _make_job(
            platform="threads",
            result_data={
                "recent_posts": [{"subreddit": "fitness"}],  # adds 'fitness' via reddit path
                "followed_topics": ["fitness", "gaming"],  # 'fitness' is already in interests
            },
        )
        # Use reddit platform so subreddit is extracted first, then followed_topics deduped
        job2 = _make_job(
            platform="reddit",
            result_data={"recent_posts": [{"subreddit": "fitness"}]},
        )
        job3 = _make_job(
            platform="threads",
            result_data={"followed_topics": ["fitness", "gaming"]},
        )
        session = _make_session(jobs=[job2, job3])
        crawler = InterestsExtractorCrawler()
        result = await crawler.scrape("00000000-0000-0000-0000-000000000003", session=session)
        assert result.found is True
        # 'fitness' appears exactly once despite being in both reddit posts and followed_topics
        assert result.data["interests"].count("fitness") == 1
        assert "gaming" in result.data["interests"]

    @pytest.mark.asyncio
    async def test_followed_topic_empty_string_skipped(self):
        """Arc 126->124: empty string topic (t is falsy) — if t: is False, loops back."""
        job = _make_job(
            platform="threads",
            result_data={"followed_topics": ["", "   ", "valid_topic"]},
        )
        session = _make_session(jobs=[job])
        crawler = InterestsExtractorCrawler()
        result = await crawler.scrape("00000000-0000-0000-0000-000000000004", session=session)
        assert result.found is True
        # Empty/whitespace topics are skipped; valid_topic is kept
        assert "valid_topic" in result.data["interests"]
        assert "" not in result.data["interests"]

    @pytest.mark.asyncio
    async def test_liked_page_already_in_interests_not_duplicated(self):
        """Arc 132->130: a liked_page already present in interests is skipped.
        The `if p and p not in interests:` condition is False — loops back to line 130."""
        job_reddit = _make_job(
            platform="reddit",
            result_data={"recent_posts": [{"subreddit": "cooking"}]},
        )
        job_fb = _make_job(
            platform="facebook",
            result_data={"liked_pages": ["cooking", "travel"]},  # 'cooking' already in interests
        )
        session = _make_session(jobs=[job_reddit, job_fb])
        crawler = InterestsExtractorCrawler()
        result = await crawler.scrape("00000000-0000-0000-0000-000000000005", session=session)
        assert result.found is True
        assert result.data["interests"].count("cooking") == 1
        assert "travel" in result.data["interests"]
