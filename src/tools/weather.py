"""WeatherTool — current weather for PKU campus (or a named city).

Uses the free, key-less 中国天气网 (China Weather) JSON API mirrored by
sojson/itboy. It is China-hosted, so it stays reachable from the campus
network where the previous source (Open-Meteo, EU-hosted) returned 502 /
timed out:

  - http://t.weather.itboy.net/api/weather/city/{code}   (primary)
  - http://t.weather.sojson.com/api/weather/city/{code}  (fallback)

`code` is a 中国天气网 city id (e.g. Haidian = ``101010200``). We default to
Haidian — PKU's district — so the common case ("北京今天天气怎么样？" while
the agent already knows the user is at PKU) returns useful data. Pass
``city`` to look elsewhere up; only major cities and Beijing districts are
mapped (see ``CITY_CODES``).

Caveats of this source vs a paid station feed: it is HTTP-only (no HTTPS),
and the condition / wind come from today's daytime *forecast* rather than a
live observation — only temperature and humidity (``data.wendu`` /
``data.shidu``) are real-time. Feels-like is derived locally via the
Australian apparent-temperature formula.
"""

from __future__ import annotations

import math
import re
from typing import Any, ClassVar

import requests

from .base import Tool, ToolResult

PKU_CITY_CODE = "101010200"  # Haidian district — PKU's home district.
PKU_LABEL = "北京大学"

API_HOSTS = (
    "http://t.weather.itboy.net",
    "http://t.weather.sojson.com",
)
API_PATH = "/api/weather/city/{code}"
DEFAULT_TIMEOUT = 10.0

# 中国天气网 city ids. Verified live against the API. Beijing districts plus
# municipalities and provincial capitals; lookup also strips 市/区/省 suffixes
# so "北京市" / "海淀区" resolve too.
CITY_CODES: dict[str, str] = {
    # Beijing + districts (PKU-relevant)
    "北京": "101010100",
    "海淀": PKU_CITY_CODE,
    "北大": PKU_CITY_CODE,
    "北京大学": PKU_CITY_CODE,
    "朝阳": "101010300",
    "顺义": "101010400",
    "怀柔": "101010500",
    "通州": "101010600",
    "昌平": "101010700",
    "延庆": "101010800",
    "丰台": "101010900",
    "石景山": "101011000",
    "大兴": "101011100",
    "房山": "101011200",
    "密云": "101011300",
    "门头沟": "101011400",
    "平谷": "101011500",
    # Municipalities
    "上海": "101020100",
    "天津": "101030100",
    "重庆": "101040100",
    # Provincial capitals / major cities
    "广州": "101280101",
    "深圳": "101280601",
    "杭州": "101210101",
    "南京": "101190101",
    "成都": "101270101",
    "武汉": "101200101",
    "西安": "101110101",
    "济南": "101120101",
    "郑州": "101180101",
    "长沙": "101250101",
    "福州": "101230101",
    "哈尔滨": "101050101",
    "沈阳": "101070101",
    "长春": "101060101",
    "石家庄": "101090101",
    "太原": "101100101",
    "合肥": "101220101",
    "南昌": "101240101",
    "南宁": "101300101",
    "海口": "101310101",
    "贵阳": "101260101",
    "昆明": "101290101",
    "拉萨": "101140101",
    "兰州": "101160101",
    "西宁": "101150101",
    "银川": "101170101",
    "乌鲁木齐": "101130101",
    "呼和浩特": "101080101",
}

# Beaufort wind force (级) -> approximate wind speed (m/s), scale midpoints.
_BEAUFORT_MS: dict[int, float] = {
    0: 0.0,
    1: 0.9,
    2: 2.5,
    3: 4.4,
    4: 6.7,
    5: 9.4,
    6: 12.3,
    7: 15.5,
    8: 18.9,
    9: 22.6,
    10: 26.5,
    11: 30.6,
    12: 34.0,
}


def resolve_city_code(city: str) -> str | None:
    """Map a free-text city name to a 中国天气网 id, or None if unknown."""
    name = (city or "").strip()
    if not name:
        return PKU_CITY_CODE
    if name in CITY_CODES:
        return CITY_CODES[name]
    trimmed = name.rstrip("市区省")
    if trimmed in CITY_CODES:
        return CITY_CODES[trimmed]
    for key, code in CITY_CODES.items():
        if key in name or name in key:
            return code
    return None


def _beaufort_to_ms(force_text: str | None) -> float:
    """Parse a wind-force string like '2级' / '3-4级' to a wind speed (m/s)."""
    if not force_text:
        return 0.0
    levels = [int(n) for n in re.findall(r"\d+", force_text)]
    if not levels:
        return 0.0
    level = max(levels)
    if level >= 12:
        return _BEAUFORT_MS[12]
    return _BEAUFORT_MS.get(level, 0.0)


def apparent_temperature_c(
    temp_c: float | None, humidity_percent: float | None, wind_ms: float
) -> float | None:
    """Australian (shade) apparent temperature — needs only T, RH, wind.

    AT = T + 0.33*e - 0.70*ws - 4.00, with e the water-vapour pressure (hPa).
    Returns None if temperature is unavailable.
    """
    if temp_c is None:
        return None
    rh = humidity_percent if humidity_percent is not None else 0.0
    e = (rh / 100.0) * 6.105 * math.exp(17.27 * temp_c / (237.7 + temp_c))
    at = temp_c + 0.33 * e - 0.70 * wind_ms - 4.00
    return round(at, 1)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip().rstrip("%℃°C "))
    except (TypeError, ValueError):
        return None


class WeatherTool(Tool):
    name: ClassVar[str] = "weather"
    description: ClassVar[str] = (
        "Return the current weather (temperature, condition, wind, humidity, air "
        "quality) for PKU campus (Haidian) by default, or for a named Chinese city "
        "when `city` is provided. Data source: 中国天气网 (no API key)."
    )
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": (
                    "Chinese city or Beijing district name (e.g. 上海, 海淀). "
                    "Defaults to PKU campus (Haidian) if omitted or empty. Only "
                    "major cities and Beijing districts are supported."
                ),
            }
        },
        "additionalProperties": False,
    }

    def __init__(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.timeout = timeout

    def invoke(self, args: dict[str, Any]) -> ToolResult:
        city = (args.get("city") or "").strip()
        code = resolve_city_code(city)
        if code is None:
            return ToolResult(
                success=False,
                error=f"暂不支持的城市：{city}（仅支持主要城市与北京各区，默认北大）",
            )
        try:
            payload = self._fetch(code)
        except requests.RequestException as exc:
            return ToolResult(success=False, error=f"网络错误：{exc}")

        if not isinstance(payload, dict) or payload.get("status") != 200:
            msg = payload.get("message") if isinstance(payload, dict) else None
            return ToolResult(success=False, error=f"天气数据异常：{msg or '未知错误'}")

        return ToolResult(success=True, data=self._shape(city, payload))

    def _fetch(self, code: str) -> dict[str, Any]:
        """Try each host in turn; raise the last error only if all fail."""
        last_exc: requests.RequestException | None = None
        for host in API_HOSTS:
            url = host + API_PATH.format(code=code)
            try:
                resp = requests.get(url, timeout=self.timeout)
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException as exc:
                last_exc = exc
                continue
        assert last_exc is not None
        raise last_exc

    def _shape(self, city: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = payload.get("data") or {}
        city_info = payload.get("cityInfo") or {}
        forecast = data.get("forecast") or []
        today = forecast[0] if forecast else {}

        # Default (no city) keeps the friendly PKU label; otherwise use the
        # API's own district/city name.
        location = PKU_LABEL if not city else (city_info.get("city") or city)

        temp_c = _to_float(data.get("wendu"))
        humidity = _to_float(data.get("shidu"))
        wind_text = " ".join(
            part for part in (today.get("fx"), today.get("fl")) if part
        ).strip()
        wind_ms = _beaufort_to_ms(today.get("fl"))

        return {
            "location": location,
            "observation_time": city_info.get("updateTime"),
            "temperature_c": temp_c,
            "apparent_temperature_c": apparent_temperature_c(
                temp_c, humidity, wind_ms
            ),
            "humidity_percent": humidity,
            "wind_speed_kmh": round(wind_ms * 3.6, 1) if wind_text else None,
            "wind": wind_text or None,
            "weather_code": None,  # WMO codes no longer apply; condition is text.
            "weather_description": today.get("type") or "未知",
            "air_quality": data.get("quality"),
            "pm25": data.get("pm25"),
            "pm10": data.get("pm10"),
            "advice": data.get("ganmao"),
            "today_high": today.get("high"),
            "today_low": today.get("low"),
        }
