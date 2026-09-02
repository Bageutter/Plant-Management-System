import io
import json

import pytest

import weather
from weather import OpenMeteoClient, WeatherUnavailableError, describe_code


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _urlopen_returning(*payloads):
    """Return a fake urlopen that yields each payload (dict) in turn, then repeats
    the last one. Records the URLs it was called with."""
    calls = []
    queue = list(payloads)

    def fake_urlopen(url, timeout=None):
        calls.append(url)
        payload = queue.pop(0) if len(queue) > 1 else queue[0]
        return FakeResponse(json.dumps(payload).encode("utf-8"))

    fake_urlopen.calls = calls
    return fake_urlopen


def test_describe_code_maps_wmo_values():
    assert describe_code(0) == "Clear sky"
    assert describe_code(95) == "Thunderstorm"
    assert describe_code(None) is None
    assert describe_code("nope") is None


def test_geocode_parses_the_top_result(monkeypatch):
    fake = _urlopen_returning(
        {
            "results": [
                {
                    "name": "Melbourne",
                    "admin1": "Victoria",
                    "country": "Australia",
                    "latitude": -37.814,
                    "longitude": 144.963,
                    "timezone": "Australia/Melbourne",
                }
            ]
        }
    )
    monkeypatch.setattr(weather.request, "urlopen", fake)

    result = OpenMeteoClient().geocode("Melbourne")

    assert result["label"] == "Melbourne, Victoria, Australia"
    assert result["latitude"] == -37.814
    assert result["timezone"] == "Australia/Melbourne"
    assert "name=Melbourne" in fake.calls[0]


def test_geocode_returns_none_on_no_match(monkeypatch):
    monkeypatch.setattr(weather.request, "urlopen", _urlopen_returning({"results": []}))
    assert OpenMeteoClient().geocode("Nowheresville") is None


def test_geocode_blank_name_short_circuits(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("should not hit the network")

    monkeypatch.setattr(weather.request, "urlopen", boom)
    assert OpenMeteoClient().geocode("   ") is None


def test_garden_weather_shapes_current_and_forecast(monkeypatch):
    fake = _urlopen_returning(
        {
            "timezone": "Europe/Berlin",
            "current": {
                "temperature_2m": 14.2,
                "apparent_temperature": 12.9,
                "relative_humidity_2m": 71,
                "precipitation": 0.0,
                "weather_code": 3,
                "wind_speed_10m": 11.0,
            },
            "daily": {
                "time": ["2026-09-03", "2026-09-04"],
                "weather_code": [61, 3],
                "temperature_2m_max": [17.0, 19.0],
                "temperature_2m_min": [9.0, 10.0],
                "precipitation_sum": [4.2, 0.0],
                "precipitation_probability_max": [80, 10],
            },
        }
    )
    monkeypatch.setattr(weather.request, "urlopen", fake)

    result = OpenMeteoClient().garden_weather(52.52, 13.40)

    assert result["current"]["temperature_c"] == 14.2
    assert result["current"]["conditions"] == "Overcast"
    assert len(result["forecast"]) == 2
    assert result["forecast"][0] == {
        "date": "2026-09-03",
        "conditions": "Slight rain",
        "temp_min_c": 9.0,
        "temp_max_c": 17.0,
        "precipitation_mm": 4.2,
        "precipitation_probability_pct": 80,
    }


def test_garden_weather_is_cached_per_rounded_coordinate(monkeypatch):
    fake = _urlopen_returning({"timezone": "UTC", "current": {}, "daily": {"time": []}})
    monkeypatch.setattr(weather.request, "urlopen", fake)
    client = OpenMeteoClient(cache_ttl=600)

    client.garden_weather(52.523, 13.401)
    client.garden_weather(52.524, 13.399)  # rounds to the same 2dp key

    assert len(fake.calls) == 1


def test_network_error_becomes_weather_unavailable(monkeypatch):
    def raise_urlerror(*a, **k):
        raise weather.error.URLError("no route to host")

    monkeypatch.setattr(weather.request, "urlopen", raise_urlerror)

    with pytest.raises(WeatherUnavailableError):
        OpenMeteoClient().geocode("Berlin")
