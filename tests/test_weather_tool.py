"""WeatherTool unit tests — no network; a captured 中国天气网 payload is fed
through a monkeypatched `_fetch` so we exercise parsing + the output-dict
contract the GUI/workflow consumers depend on."""

from __future__ import annotations

import pytest

from src.tools.weather import (
    PKU_CITY_CODE,
    PKU_LABEL,
    WeatherTool,
    apparent_temperature_c,
    resolve_city_code,
)

# Trimmed but real-shaped 中国天气网 envelope (Haidian).
SAMPLE = {
    "message": "success",
    "status": 200,
    "cityInfo": {
        "city": "海淀区",
        "citykey": "101010200",
        "parent": "北京市",
        "updateTime": "18:17",
    },
    "data": {
        "shidu": "44%",
        "pm25": 13.0,
        "pm10": 23.0,
        "quality": "优",
        "wendu": "22.6",
        "ganmao": "各类人群可自由活动",
        "forecast": [
            {"type": "大雨", "fx": "东北风", "fl": "2级", "high": "高温 31℃", "low": "低温 21℃"},
        ],
    },
}


@pytest.fixture
def tool(monkeypatch: pytest.MonkeyPatch) -> WeatherTool:
    t = WeatherTool()
    monkeypatch.setattr(t, "_fetch", lambda code: SAMPLE)
    return t


def test_resolve_city_code_default_is_pku() -> None:
    assert resolve_city_code("") == PKU_CITY_CODE
    assert resolve_city_code("海淀区") == PKU_CITY_CODE
    assert resolve_city_code("北京大学") == PKU_CITY_CODE
    assert resolve_city_code("上海市") == "101020100"
    assert resolve_city_code("不存在xyz") is None


def test_invoke_default_shapes_contract_keys(tool: WeatherTool) -> None:
    result = tool.invoke({})
    assert result.success
    data = result.data
    # Keys the GUI/workflow consumers read.
    for key in (
        "location",
        "temperature_c",
        "apparent_temperature_c",
        "humidity_percent",
        "wind_speed_kmh",
        "weather_code",
        "weather_description",
    ):
        assert key in data
    assert data["location"] == PKU_LABEL  # empty city -> friendly PKU label
    assert data["temperature_c"] == 22.6
    assert data["humidity_percent"] == 44.0
    assert data["weather_description"] == "大雨"
    assert data["wind"] == "东北风 2级"
    assert data["weather_code"] is None
    assert isinstance(data["apparent_temperature_c"], float)


def test_invoke_named_city_uses_api_city_name(tool: WeatherTool) -> None:
    result = tool.invoke({"city": "海淀"})
    assert result.success
    assert result.data["location"] == "海淀区"  # not the PKU label


def test_invoke_unknown_city_fails_cleanly() -> None:
    result = WeatherTool().invoke({"city": "不存在xyz"})
    assert not result.success
    assert "暂不支持" in (result.error or "")


def test_bad_status_payload_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    t = WeatherTool()
    monkeypatch.setattr(t, "_fetch", lambda code: {"status": 500, "message": "boom"})
    result = t.invoke({})
    assert not result.success
    assert "天气数据异常" in (result.error or "")


def test_apparent_temperature_formula() -> None:
    assert apparent_temperature_c(None, 50.0, 1.0) is None
    # Warmer + humid reads hotter than dry; both finite floats.
    humid = apparent_temperature_c(30.0, 80.0, 0.0)
    dry = apparent_temperature_c(30.0, 20.0, 0.0)
    assert humid is not None and dry is not None
    assert humid > dry
