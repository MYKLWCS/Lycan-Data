import pytest

from shared.health import check_bypass_layers


@pytest.mark.asyncio
async def test_check_bypass_layers_returns_dict():
    result = await check_bypass_layers()
    assert isinstance(result, dict)
    expected_keys = {"flaresolverr", "tor_1", "tor_2", "tor_3", "dragonfly", "postgres"}
    assert expected_keys.issubset(result.keys())


@pytest.mark.asyncio
async def test_check_bypass_layers_values_are_bool():
    result = await check_bypass_layers()
    for v in result.values():
        assert isinstance(v, bool)
