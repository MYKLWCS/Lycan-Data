"""Tests for modules/patterns/inverted_index.py — AttributeInvertedIndex.

All Redis calls are mocked — no live Dragonfly/Redis required.
"""

from unittest.mock import AsyncMock, call

import pytest

from modules.patterns.inverted_index import _EXPIRY_SECONDS, AttributeInvertedIndex


def _make_redis() -> AsyncMock:
    redis = AsyncMock()
    redis.sadd = AsyncMock(return_value=1)
    redis.expire = AsyncMock(return_value=1)
    redis.smembers = AsyncMock(return_value=set())
    redis.sinter = AsyncMock(return_value=set())
    redis.srem = AsyncMock(return_value=1)
    return redis


# ---------------------------------------------------------------------------
# index_entity
# ---------------------------------------------------------------------------


async def test_index_entity_scalar_fields():
    redis = _make_redis()
    idx = AttributeInvertedIndex(redis)
    await idx.index_entity("e1", {"name": "Alice", "score": 0.9})
    # sadd should be called once per non-None scalar field
    assert redis.sadd.call_count == 2
    assert redis.expire.call_count == 2


async def test_index_entity_list_field():
    redis = _make_redis()
    idx = AttributeInvertedIndex(redis)
    await idx.index_entity("e1", {"phones": ["111", "222"]})
    assert redis.sadd.call_count == 2


async def test_index_entity_dict_field():
    redis = _make_redis()
    idx = AttributeInvertedIndex(redis)
    await idx.index_entity("e1", {"address": {"city": "NY", "state": "NY"}})
    # address.city and address.state → 2 sadd calls
    assert redis.sadd.call_count == 2


async def test_index_entity_skips_none_values():
    redis = _make_redis()
    idx = AttributeInvertedIndex(redis)
    await idx.index_entity("e1", {"name": None, "score": None})
    assert redis.sadd.call_count == 0


async def test_index_entity_key_format():
    redis = _make_redis()
    idx = AttributeInvertedIndex(redis)
    await idx.index_entity("e1", {"email": "a@b.com"})
    key_used = redis.sadd.call_args[0][0]
    assert key_used == "lycan:attr:email:a@b.com"
    assert redis.sadd.call_args[0][1] == "e1"


async def test_index_entity_redis_error_does_not_raise():
    redis = _make_redis()
    redis.sadd = AsyncMock(side_effect=Exception("connection refused"))
    idx = AttributeInvertedIndex(redis)
    # Should swallow the exception gracefully
    await idx.index_entity("e1", {"name": "Bob"})


# ---------------------------------------------------------------------------
# find_entities
# ---------------------------------------------------------------------------


async def test_find_entities_returns_set_of_strings():
    redis = _make_redis()
    redis.smembers = AsyncMock(return_value={b"e1", b"e2"})
    idx = AttributeInvertedIndex(redis)
    result = await idx.find_entities("email", "a@b.com")
    assert result == {"e1", "e2"}


async def test_find_entities_decodes_bytes():
    redis = _make_redis()
    redis.smembers = AsyncMock(return_value={b"entity-uuid-1"})
    idx = AttributeInvertedIndex(redis)
    result = await idx.find_entities("phone", "555-1234")
    assert "entity-uuid-1" in result


async def test_find_entities_redis_error_returns_empty_set():
    redis = _make_redis()
    redis.smembers = AsyncMock(side_effect=Exception("timeout"))
    idx = AttributeInvertedIndex(redis)
    result = await idx.find_entities("phone", "555-0000")
    assert result == set()


# ---------------------------------------------------------------------------
# find_co_occurrence
# ---------------------------------------------------------------------------


async def test_find_co_occurrence_returns_intersection():
    redis = _make_redis()
    redis.sinter = AsyncMock(return_value={b"shared-entity"})
    idx = AttributeInvertedIndex(redis)
    result = await idx.find_co_occurrence("email", "a@b.com", "phone", "555-1111")
    assert result == {"shared-entity"}


async def test_find_co_occurrence_redis_error_returns_empty_set():
    redis = _make_redis()
    redis.sinter = AsyncMock(side_effect=Exception("network error"))
    idx = AttributeInvertedIndex(redis)
    result = await idx.find_co_occurrence("email", "a@b.com", "phone", "555-1111")
    assert result == set()


# ---------------------------------------------------------------------------
# remove_entity / remove_entity_from_field
# ---------------------------------------------------------------------------


async def test_remove_entity_calls_srem_with_correct_key():
    redis = _make_redis()
    idx = AttributeInvertedIndex(redis)
    await idx.remove_entity("e1", "email", "a@b.com")
    redis.srem.assert_called_once_with("lycan:attr:email:a@b.com", "e1")


async def test_remove_entity_from_field_mirrors_index_entity():
    redis = _make_redis()
    idx = AttributeInvertedIndex(redis)
    data = {"name": "Alice", "tags": ["vip", "verified"], "loc": {"city": "NY"}}
    await idx.remove_entity_from_field("e1", data)
    # name → 1, tags → 2, loc.city → 1 = 4 srem calls
    assert redis.srem.call_count == 4


async def test_remove_entity_redis_error_does_not_raise():
    redis = _make_redis()
    redis.srem = AsyncMock(side_effect=Exception("write error"))
    idx = AttributeInvertedIndex(redis)
    await idx.remove_entity("e1", "name", "Alice")
