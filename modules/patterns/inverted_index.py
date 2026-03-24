"""Inverted attribute index — Redis/Dragonfly-backed for reverse entity lookups."""
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_EXPIRY_SECONDS = 86400 * 30  # 30 days


class AttributeInvertedIndex:
    """
    Index entity attributes for O(1) reverse lookups: given a value, find all entities.

    Key schema:
        lycan:attr:{field}:{value}  ->  Redis SET of entity_ids
    """

    def __init__(self, redis_client) -> None:
        self.redis = redis_client

    async def index_entity(self, entity_id: str, entity_data: dict[str, Any]) -> None:
        """Index all scalar and list attributes of an entity."""
        for field, value in entity_data.items():
            if value is None:
                continue
            if isinstance(value, (str, int, float, bool)):
                await self._index_value(field, str(value), entity_id)
            elif isinstance(value, list):
                for item in value:
                    if item is not None:
                        await self._index_value(field, str(item), entity_id)
            elif isinstance(value, dict):
                for k, v in value.items():
                    if v is not None:
                        await self._index_value(f"{field}.{k}", str(v), entity_id)

    async def _index_value(self, field: str, value: str, entity_id: str) -> None:
        key = f"lycan:attr:{field}:{value[:200]}"  # cap key length
        try:
            await self.redis.sadd(key, entity_id)
            await self.redis.expire(key, _EXPIRY_SECONDS)
        except Exception:
            logger.exception("AttributeInvertedIndex._index_value failed field=%s", field)

    async def find_entities(self, field: str, value: str) -> set[str]:
        """Return all entity_ids with this field=value."""
        key = f"lycan:attr:{field}:{str(value)[:200]}"
        try:
            members = await self.redis.smembers(key)
            return {m.decode() if isinstance(m, bytes) else m for m in (members or set())}
        except Exception:
            logger.exception("AttributeInvertedIndex.find_entities failed")
            return set()

    async def find_co_occurrence(
        self, field1: str, value1: str, field2: str, value2: str
    ) -> set[str]:
        """Find entities sharing two specific attributes."""
        key1 = f"lycan:attr:{field1}:{str(value1)[:200]}"
        key2 = f"lycan:attr:{field2}:{str(value2)[:200]}"
        try:
            result = await self.redis.sinter(key1, key2)
            return {m.decode() if isinstance(m, bytes) else m for m in (result or set())}
        except Exception:
            logger.exception("AttributeInvertedIndex.find_co_occurrence failed")
            return set()

    async def remove_entity(self, entity_id: str, field: str, value: str) -> None:
        """Remove a specific entity from an attribute index entry."""
        key = f"lycan:attr:{field}:{str(value)[:200]}"
        try:
            await self.redis.srem(key, entity_id)
        except Exception:
            logger.exception("AttributeInvertedIndex.remove_entity failed")
