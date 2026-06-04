"""WeatherTool — real-time weather for PKU campus (or a named city).

Uses wttr.in's key-less JSON API (``?format=j1``), which exposes a genuine
**current** observation (``current_condition``) rather than a daily forecast.
The previous 中国天气网 mirror served today's daytime forecast as "current",
so it would report e.g. 大雨 on a dry afternoon; wttr.in fixes that.

  - Default (no city): pinned to PKU coordinates so it resolves to Haidian.
  - ``city``: passed straight to wttr.in, which geocodes Chinese or English
    names ("上海" / "Shanghai" both work).

Tradeoffs (accepted, see CLAUDE.md): wttr.in is a foreign-hosted hobby
service backed by a global weather model, so it is less precise for China
than a paid station feed (和风 / 高德) and can occasionally rate-limit — we
retry once. It reachable from the campus network where Open-Meteo is not.

Conditions arrive as numeric WWO weather codes, which we map to Chinese so
the dashboard icon logic (keyed on 雨/雪/雷/晴/… in the text) keeps working.
"""

from __future__ import annotations

from typing import Any, ClassVar

import requests

from .base import Tool, ToolResult

PKU_LATITUDE = 39.9904
PKU_LONGITUDE = 116.3076
PKU_LABEL = "北京大学"

WTTR_URL = "https://wttr.in/{location}"
DEFAULT_TIMEOUT = 15.0
_RETRIES = 1  # wttr.in occasionally rate-limits; one retry covers transient 5xx.

# WWO weather codes -> Chinese. Strings are chosen so the dashboard's
# `_weather_icon` keyword match (雷 > 雪 > 雨 > 阴 > 雾 > 晴) lands sensibly.
_WWO_CODES_ZH: dict[int, str] = {
    113: "晴",
    116: "晴间多云",
    119: "多云",
    122: "阴",
    143: "薄雾",
    176: "局部有雨",
    179: "局部有雪",
    182: "局部雨夹雪",
    185: "局部冻毛毛雨",
    200: "局部雷阵雨",
    227: "吹雪",
    230: "暴雪",
    248: "雾",
    260: "冻雾",
    263: "局部小毛毛雨",
    266: "小毛毛雨",
    281: "冻毛毛雨",
    284: "强冻毛毛雨",
    293: "局部小雨",
    296: "小雨",
    299: "间歇中雨",
    302: "中雨",
    305: "间歇大雨",
    308: "大雨",
    311: "小冻雨",
    314: "中到大冻雨",
    317: "小雨夹雪",
    320: "中到大雨夹雪",
    323: "局部小雪",
    326: "小雪",
    329: "局部中雪",
    332: "中雪",
    335: "局部大雪",
    338: "大雪",
    350: "冰粒",
    353: "小阵雨",
    356: "中到大阵雨",
    359: "暴雨",
    362: "小阵雨夹雪",
    365: "中到大阵雨夹雪",
    368: "小阵雪",
    371: "中到大阵雪",
    374: "小冰粒阵雨",
    377: "中到大冰粒阵雨",
    386: "局部雷阵雨",
    389: "强雷阵雨",
    392: "局部雷雪",
    395: "强雷雪",
}


def describe_weather_code(code: Any, fallback: str = "未知") -> str:
    """Map a WWO weather code to Chinese, falling back to a supplied string."""
    try:
        return _WWO_CODES_ZH.get(int(code), fallback)
    except (TypeError, ValueError):
        return fallback


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _first_value(items: Any) -> str | None:
    """wttr.in nests labels as ``[{"value": ...}]``; pull the first value."""
    if isinstance(items, list) and items and isinstance(items[0], dict):
        return items[0].get("value")
    return None


class WeatherTool(Tool):
    name: ClassVar[str] = "weather"
    description: ClassVar[str] = (
        "Return the current real-time weather (temperature, condition, feels-like, "
        "wind, humidity) for PKU campus by default, or for a named city when `city` "
        "is provided. Data source: wttr.in (no API key)."
    )
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": (
                    "City name to look up (Chinese or English, e.g. 上海 / Shanghai). "
                    "Defaults to PKU campus (Haidian) if omitted or empty."
                ),
            }
        },
        "additionalProperties": False,
    }

    def __init__(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.timeout = timeout

    def invoke(self, args: dict[str, Any]) -> ToolResult:
        city = (args.get("city") or "").strip()
        query = city if city else f"{PKU_LATITUDE},{PKU_LONGITUDE}"
        try:
            payload = self._fetch(query)
        except requests.RequestException as exc:
            return ToolResult(success=False, error=f"网络错误：{exc}")

        conditions = payload.get("current_condition") if isinstance(payload, dict) else None
        if not isinstance(conditions, list) or not conditions:
            return ToolResult(success=False, error=f"找不到城市或天气数据：{city or 'PKU'}")

        return ToolResult(success=True, data=self._shape(city, payload, conditions[0]))

    def _fetch(self, query: str) -> dict[str, Any]:
        url = WTTR_URL.format(location=query)
        last_exc: requests.RequestException | None = None
        for _ in range(_RETRIES + 1):
            try:
                resp = requests.get(
                    url,
                    params={"format": "j1"},
                    timeout=self.timeout,
                    headers={"User-Agent": "curl/8"},  # wttr.in serves JSON to curl-like UAs.
                )
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException as exc:
                last_exc = exc
        assert last_exc is not None
        raise last_exc

    def _shape(
        self, city: str, payload: dict[str, Any], current: dict[str, Any]
    ) -> dict[str, Any]:
        # Echo the user's city (keeps Chinese input intact) — wttr.in's
        # nearest_area name is English ("上海" -> "Pootung"), poor for a
        # Chinese-facing product. Default (no city) uses the friendly label.
        location = city if city else PKU_LABEL

        code = current.get("weatherCode")
        wind_dir = current.get("winddir16Point")
        wind_kmh = _to_float(current.get("windspeedKmph"))
        wind = (
            f"{wind_dir} {wind_kmh:g}km/h"
            if wind_dir and wind_kmh is not None
            else None
        )

        return {
            "location": location,
            "observation_time": current.get("observation_time"),
            "temperature_c": _to_float(current.get("temp_C")),
            "apparent_temperature_c": _to_float(current.get("FeelsLikeC")),
            "humidity_percent": _to_float(current.get("humidity")),
            "wind_speed_kmh": wind_kmh,
            "wind": wind,
            "weather_code": int(code) if str(code).isdigit() else None,
            "weather_description": describe_weather_code(
                code, fallback=_first_value(current.get("weatherDesc")) or "未知"
            ),
            "precip_mm": _to_float(current.get("precipMM")),
            "visibility_km": _to_float(current.get("visibility")),
            "pressure_hpa": _to_float(current.get("pressure")),
            "uv_index": _to_float(current.get("uvIndex")),
            "cloud_cover_percent": _to_float(current.get("cloudcover")),
        }
