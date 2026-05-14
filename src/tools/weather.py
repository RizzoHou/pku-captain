"""WeatherTool — current weather for PKU campus (or any city).

Uses Open-Meteo's free, key-less HTTP API:

  - Geocoding:  https://geocoding-api.open-meteo.com/v1/search
  - Forecast :  https://api.open-meteo.com/v1/forecast

Defaults to PKU's coordinates (39.99°N, 116.31°E) so the common case
("北京今天天气怎么样？" while the agent already knows the user is at PKU)
returns useful data without a geocoding round-trip. Pass ``city`` to
look somewhere else up.
"""

from __future__ import annotations

from typing import Any, ClassVar

import requests

from .base import Tool, ToolResult

PKU_LATITUDE = 39.9904
PKU_LONGITUDE = 116.3076
PKU_LABEL = "北京大学"

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
DEFAULT_TIMEOUT = 15.0

# WMO weather interpretation codes — Open-Meteo follows the standard.
_WEATHER_CODES_ZH: dict[int, str] = {
    0: "晴",
    1: "晴间多云",
    2: "多云",
    3: "阴",
    45: "雾",
    48: "雾凇",
    51: "毛毛雨（小）",
    53: "毛毛雨（中）",
    55: "毛毛雨（大）",
    56: "冻毛毛雨（小）",
    57: "冻毛毛雨（大）",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨（小）",
    67: "冻雨（大）",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "雪粒",
    80: "阵雨（小）",
    81: "阵雨（中）",
    82: "阵雨（大）",
    85: "阵雪（小）",
    86: "阵雪（大）",
    95: "雷暴",
    96: "雷暴伴小冰雹",
    99: "雷暴伴大冰雹",
}


def describe_weather_code(code: int | None) -> str:
    if code is None:
        return "未知"
    return _WEATHER_CODES_ZH.get(int(code), f"未知天气代码 {code}")


class WeatherTool(Tool):
    name: ClassVar[str] = "weather"
    description: ClassVar[str] = (
        "Return the current weather (temperature, condition, wind, humidity) for "
        "PKU campus by default, or for a named city when `city` is provided. "
        "Data source: Open-Meteo (no API key)."
    )
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": (
                    "City name to look up via Open-Meteo geocoding. Defaults to "
                    "PKU campus coordinates if omitted or empty."
                ),
            }
        },
        "additionalProperties": False,
    }

    def __init__(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.timeout = timeout

    def invoke(self, args: dict[str, Any]) -> ToolResult:
        city = (args.get("city") or "").strip()
        try:
            if city:
                location = self._geocode(city)
                if location is None:
                    return ToolResult(
                        success=False, error=f"找不到城市：{city}"
                    )
            else:
                location = {
                    "name": PKU_LABEL,
                    "latitude": PKU_LATITUDE,
                    "longitude": PKU_LONGITUDE,
                }
            current = self._fetch_current(
                latitude=location["latitude"],
                longitude=location["longitude"],
            )
        except requests.RequestException as exc:
            return ToolResult(success=False, error=f"网络错误：{exc}")

        return ToolResult(
            success=True,
            data={
                "location": location["name"],
                "latitude": location["latitude"],
                "longitude": location["longitude"],
                "observation_time": current.get("time"),
                "temperature_c": current.get("temperature_2m"),
                "apparent_temperature_c": current.get("apparent_temperature"),
                "humidity_percent": current.get("relative_humidity_2m"),
                "wind_speed_kmh": current.get("wind_speed_10m"),
                "weather_code": current.get("weather_code"),
                "weather_description": describe_weather_code(
                    current.get("weather_code")
                ),
            },
        )

    def _geocode(self, city: str) -> dict[str, Any] | None:
        resp = requests.get(
            GEOCODE_URL,
            params={"name": city, "count": 1, "language": "zh", "format": "json"},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        results = resp.json().get("results") or []
        if not results:
            return None
        top = results[0]
        return {
            "name": top.get("name", city),
            "latitude": top["latitude"],
            "longitude": top["longitude"],
        }

    def _fetch_current(self, *, latitude: float, longitude: float) -> dict[str, Any]:
        resp = requests.get(
            FORECAST_URL,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "current": ",".join(
                    [
                        "temperature_2m",
                        "apparent_temperature",
                        "relative_humidity_2m",
                        "weather_code",
                        "wind_speed_10m",
                    ]
                ),
                "timezone": "Asia/Shanghai",
                "wind_speed_unit": "kmh",
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json().get("current") or {}
