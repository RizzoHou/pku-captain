"""WeatherTool unit tests — no network; a captured wttr.in j1 payload is fed
through a monkeypatched `_fetch` so we exercise parsing + the output-dict
contract the GUI/workflow consumers depend on."""

from __future__ import annotations

import pytest

from src.tools.weather import (
    PKU_LABEL,
    WeatherTool,
    describe_weather_code,
)

# Trimmed but real-shaped wttr.in ?format=j1 envelope.
SAMPLE = {
    "current_condition": [
        {
            "temp_C": "18",
            "FeelsLikeC": "17",
            "humidity": "83",
            "weatherCode": "308",
            "weatherDesc": [{"value": "Heavy rain"}],
            "windspeedKmph": "12",
            "winddir16Point": "E",
            "observation_time": "01:40 PM",
            "precipMM": "2.1",
            "visibility": "8",
            "pressure": "1009",
            "uvIndex": "0",
            "cloudcover": "75",
        }
    ],
    "nearest_area": [
        {
            "areaName": [{"value": "Haidian"}],
            "region": [{"value": "Beijing"}],
        }
    ],
}


@pytest.fixture
def tool(monkeypatch: pytest.MonkeyPatch) -> WeatherTool:
    t = WeatherTool()
    monkeypatch.setattr(t, "_fetch", lambda query: SAMPLE)
    return t


def test_describe_weather_code() -> None:
    assert describe_weather_code("113") == "晴"
    assert describe_weather_code(308) == "大雨"
    assert describe_weather_code(99999, fallback="Clear") == "Clear"
    assert describe_weather_code(None) == "未知"


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
    assert data["temperature_c"] == 18.0
    assert data["apparent_temperature_c"] == 17.0  # wttr.in feels-like, not derived
    assert data["humidity_percent"] == 83.0
    assert data["weather_code"] == 308
    assert data["weather_description"] == "大雨"  # mapped from WWO code
    assert data["wind"] == "E 12km/h"


def test_invoke_named_city_echoes_input(tool: WeatherTool) -> None:
    result = tool.invoke({"city": "海淀"})
    assert result.success
    assert result.data["location"] == "海淀"  # echoes user input, not the PKU label


def test_unknown_code_falls_back_to_english_desc(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "current_condition": [
            {"temp_C": "20", "weatherCode": "99999", "weatherDesc": [{"value": "Sandstorm"}]}
        ]
    }
    t = WeatherTool()
    monkeypatch.setattr(t, "_fetch", lambda query: payload)
    result = t.invoke({})
    assert result.success
    assert result.data["weather_description"] == "Sandstorm"
    assert result.data["weather_code"] == 99999  # raw WWO code kept even when unmapped


def test_empty_conditions_fails_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    t = WeatherTool()
    monkeypatch.setattr(t, "_fetch", lambda query: {"current_condition": []})
    result = t.invoke({"city": "Nowhereville"})
    assert not result.success
    assert "找不到" in (result.error or "")
