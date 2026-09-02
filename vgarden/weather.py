"""Open-Meteo client for garden location + weather.

Open-Meteo (https://open-meteo.com) needs no API key for non-commercial use, so
this only needs outbound internet access. Used in two places:

  * garden creation / editing: turn a typed place name into coordinates + a
    tidy label (``geocode``);
  * the garden AI assistant: a compact current-conditions + short-forecast
    snapshot for the garden's coordinates (``garden_weather``), lightly cached
    so a burst of chat messages doesn't hammer the API.
"""

import json
import time
from datetime import datetime, timezone
from urllib import error, parse, request

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather interpretation codes used by Open-Meteo.
# https://open-meteo.com/en/docs#weathervariables
WEATHER_CODES = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow fall",
    73: "Moderate snow fall",
    75: "Heavy snow fall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


class WeatherUnavailableError(RuntimeError):
    """Open-Meteo could not be reached or returned something unusable."""


def describe_code(code) -> str | None:
    try:
        return WEATHER_CODES.get(int(code))
    except (TypeError, ValueError):
        return None


class OpenMeteoClient:
    def __init__(
        self,
        geocoding_url: str = GEOCODING_URL,
        forecast_url: str = FORECAST_URL,
        timeout: int = 10,
        cache_ttl: int = 1800,
        forecast_days: int = 7,
    ):
        self.geocoding_url = geocoding_url
        self.forecast_url = forecast_url
        self.timeout = timeout
        self.cache_ttl = cache_ttl
        self.forecast_days = forecast_days
        self._cache: dict[tuple[float, float], tuple[float, dict]] = {}

    # -- HTTP ---------------------------------------------------------------

    def _get(self, url: str, params: dict) -> dict:
        query = parse.urlencode({k: v for k, v in params.items() if v is not None})
        try:
            with request.urlopen(f"{url}?{query}", timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (error.URLError, TimeoutError, ValueError) as exc:
            raise WeatherUnavailableError(str(exc)) from exc

    # -- geocoding --------------------------------------------------------

    def geocode(self, name: str) -> dict | None:
        """Resolve a place name to coordinates. Returns None if nothing matched."""
        name = (name or "").strip()
        if not name:
            return None

        data = self._get(
            self.geocoding_url, {"name": name, "count": 1, "language": "en", "format": "json"}
        )
        results = data.get("results") or []
        if not results:
            return None

        top = results[0]
        label = ", ".join(
            part
            for part in (top.get("name"), top.get("admin1"), top.get("country"))
            if part
        )
        return {
            "label": label or name,
            "latitude": top["latitude"],
            "longitude": top["longitude"],
            "timezone": top.get("timezone"),
        }

    # -- weather --------------------------------------------------------

    def garden_weather(self, latitude: float, longitude: float) -> dict:
        """Compact current-conditions + daily forecast for the garden's location.

        Cached per rounded coordinate for ``cache_ttl`` seconds.
        """
        key = (round(float(latitude), 2), round(float(longitude), 2))
        hit = self._cache.get(key)
        if hit and (time.monotonic() - hit[0]) < self.cache_ttl:
            return hit[1]

        data = self._get(
            self.forecast_url,
            {
                "latitude": latitude,
                "longitude": longitude,
                "current": ",".join(
                    [
                        "temperature_2m",
                        "apparent_temperature",
                        "relative_humidity_2m",
                        "precipitation",
                        "weather_code",
                        "wind_speed_10m",
                    ]
                ),
                "daily": ",".join(
                    [
                        "weather_code",
                        "temperature_2m_max",
                        "temperature_2m_min",
                        "precipitation_sum",
                        "precipitation_probability_max",
                    ]
                ),
                "forecast_days": self.forecast_days,
                "timezone": "auto",
            },
        )

        weather = {
            "as_of": datetime.now(timezone.utc).isoformat(timespec="minutes"),
            "timezone": data.get("timezone"),
            "current": _current(data.get("current") or {}),
            "forecast": _forecast(data.get("daily") or {}),
        }
        self._cache[key] = (time.monotonic(), weather)
        return weather


def _current(current: dict) -> dict:
    return {
        "temperature_c": current.get("temperature_2m"),
        "feels_like_c": current.get("apparent_temperature"),
        "relative_humidity_pct": current.get("relative_humidity_2m"),
        "precipitation_mm": current.get("precipitation"),
        "wind_speed_kmh": current.get("wind_speed_10m"),
        "conditions": describe_code(current.get("weather_code")),
    }


def _forecast(daily: dict) -> list[dict]:
    dates = daily.get("time") or []

    def col(name: str) -> list:
        return daily.get(name) or [None] * len(dates)

    codes = col("weather_code")
    tmax = col("temperature_2m_max")
    tmin = col("temperature_2m_min")
    precip = col("precipitation_sum")
    precip_prob = col("precipitation_probability_max")

    return [
        {
            "date": date,
            "conditions": describe_code(codes[i]),
            "temp_min_c": tmin[i],
            "temp_max_c": tmax[i],
            "precipitation_mm": precip[i],
            "precipitation_probability_pct": precip_prob[i],
        }
        for i, date in enumerate(dates)
    ]
