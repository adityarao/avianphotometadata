# © Aditya Rao (aditya.r.rao@gmail.com)
"""
WeatherService — historical weather lookup via Open-Meteo archive API.

Flow per photo
--------------
1. Parse photo timestamp → local date + hour
2. Check weather_cache (lat/lon rounded to 2dp, date, timezone)
3. Cache miss → call Open-Meteo archive API
4. Match nearest hourly row to the photo's local hour
5. Store full raw JSON in cache (so other photos same day/loc reuse it)
6. Return WeatherResult dict

Fields returned match the screenshot the user shared:
  condition, temperature_c, wind_label, wind_dir, cloud_cover_pct,
  relative_humidity, sunrise, sunset
  + raw numeric fields for template rendering
"""

import json
import math
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Optional

from services.db_service import DatabaseService
from services.template_service import wmo_label, beaufort_label, cardinal_direction

# ---------------------------------------------------------------------------
# API endpoint
# ---------------------------------------------------------------------------

_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

_HOURLY_VARS = [
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "cloud_cover",
    "wind_speed_10m",
    "wind_direction_10m",
    "weather_code",
]

_DAILY_VARS = ["sunrise", "sunset"]


# ---------------------------------------------------------------------------
# WeatherService
# ---------------------------------------------------------------------------

class WeatherService:

    def __init__(self, db: DatabaseService):
        self._db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def lookup(
        self,
        lat: float,
        lon: float,
        photo_datetime_str: str,   # EXIF "2026:06:18 07:42:00"
        timezone_str: str = "auto",  # IANA name, EXIF offset, or "auto"
    ) -> tuple[Optional[dict], Optional[str]]:
        """
        Return (weather_dict, error_message).
        weather_dict is None on failure; error_message explains why.
        Always checks cache first; falls back to network call.
        """
        dt = _parse_exif_dt(photo_datetime_str)
        if dt is None:
            return None, "Could not parse photo timestamp."

        date_str   = dt.strftime("%Y-%m-%d")
        photo_hour = dt.hour

        # Open-Meteo requires an IANA timezone name (e.g. "Asia/Kolkata")
        # or the special value "auto". EXIF offsets like "+05:30" are invalid.
        # We always use "auto" for the API call; the cache key uses "auto" too.
        api_tz     = "auto"
        cache_key  = "auto"

        # Cache check
        cached = self._db.get_weather_cache(lat, lon, date_str, cache_key)
        if cached:
            return self._pick_hour(cached, photo_hour, from_cache=True), None

        # Network call
        raw, err = self._fetch(lat, lon, date_str, api_tz)
        if raw is None:
            return None, err

        self._db.save_weather_cache(lat, lon, date_str, cache_key, {
            "source":     "Open-Meteo Historical Weather API",
            "raw_json":   raw,
            "confidence": "estimated",
        })

        return self._pick_hour({"raw_json": raw}, photo_hour, from_cache=False), None

    # ------------------------------------------------------------------
    # Internal — network
    # ------------------------------------------------------------------

    def _fetch(
        self, lat: float, lon: float, date: str, tz: str
    ) -> tuple[Optional[dict], Optional[str]]:
        """Return (parsed_json, error_string). Both set on failure."""
        params = {
            "latitude":   f"{lat:.4f}",
            "longitude":  f"{lon:.4f}",
            "start_date": date,
            "end_date":   date,
            "hourly":     ",".join(_HOURLY_VARS),
            "daily":      ",".join(_DAILY_VARS),
            "timezone":   tz,
        }
        url = _ARCHIVE_URL + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "AvianPhotoMetadataAssistant/1.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode()), None
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:300]
            return None, f"HTTP {e.code}: {body}"
        except urllib.error.URLError as e:
            return None, f"Network error: {e.reason}"
        except Exception as e:
            return None, f"Unexpected error: {e}"

    # ------------------------------------------------------------------
    # Internal — parse raw JSON → single-hour result
    # ------------------------------------------------------------------

    def _pick_hour(self, cached_row: dict, photo_hour: int, from_cache: bool) -> Optional[dict]:
        """
        Extract the hourly row nearest to photo_hour from raw_json.
        cached_row is either the DB row dict or {"raw_json": <dict>}.
        """
        raw = cached_row.get("raw_json")
        if raw is None:
            return None

        # raw_json may be a dict (just fetched) or already parsed (from DB)
        if isinstance(raw, str):
            raw = json.loads(raw)

        hourly = raw.get("hourly", {})
        times  = hourly.get("time", [])
        if not times:
            return None

        # Find index of the hour closest to photo_hour
        best_idx, best_diff = 0, 24
        for i, t in enumerate(times):
            try:
                h = int(t[11:13])   # "2026-06-18T07:00" → 7
                diff = abs(h - photo_hour)
                if diff < best_diff:
                    best_diff, best_idx = diff, i
            except (ValueError, IndexError):
                continue

        def hval(key):
            arr = hourly.get(key, [])
            return arr[best_idx] if best_idx < len(arr) else None

        temp  = hval("temperature_2m")
        hum   = hval("relative_humidity_2m")
        prec  = hval("precipitation")
        cloud = hval("cloud_cover")
        wspd  = hval("wind_speed_10m")
        wdir  = hval("wind_direction_10m")
        code  = hval("weather_code")

        # Sunrise / sunset from daily section
        daily   = raw.get("daily", {})
        sunrise = _fmt_time(daily.get("sunrise", [None])[0])
        sunset  = _fmt_time(daily.get("sunset",  [None])[0])

        matched_time = times[best_idx] if best_idx < len(times) else None

        return {
            "source":             "Open-Meteo Historical Weather API",
            "matched_time":       matched_time,
            "from_cache":         from_cache,
            "confidence":         "estimated",

            # Numeric fields (for template math)
            "temperature_c":      temp,
            "relative_humidity":  hum,
            "precipitation_mm":   prec,
            "cloud_cover_pct":    cloud,
            "wind_speed_kmh":     wspd,
            "wind_direction_deg": wdir,
            "weather_code":       code,

            # Display-ready strings
            "condition":    wmo_label(code)          or "—",
            "wind_label":   beaufort_label(wspd)     or "—",
            "wind_dir":     cardinal_direction(wdir) or "—",
            "sunrise":      sunrise or "—",
            "sunset":       sunset  or "—",
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_exif_dt(dt_str: str) -> Optional[datetime]:
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(dt_str[:19], fmt)
        except ValueError:
            continue
    return None


def _fmt_time(iso_str: Optional[str]) -> Optional[str]:
    """'2026-06-18T06:34' → '6:34 am'"""
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%-I:%M %p").lower()
    except Exception:
        return iso_str
