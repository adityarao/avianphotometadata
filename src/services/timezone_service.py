# © Aditya Rao (aditya.r.rao@gmail.com)
"""
TimezoneService — infer IANA timezone from GPS coordinates.

Uses timezonefinder (offline, bundled timezone polygons).
Falls back gracefully if the library isn't installed or coords are missing.
"""

from typing import Optional

# Common birding timezones shown in the UI dropdown
COMMON_TIMEZONES = [
    # South Asia
    "Asia/Kolkata",
    "Asia/Kathmandu",
    "Asia/Colombo",
    "Asia/Dhaka",
    # Southeast Asia
    "Asia/Rangoon",
    "Asia/Bangkok",
    "Asia/Singapore",
    "Asia/Jakarta",
    "Asia/Manila",
    # East Asia
    "Asia/Tokyo",
    "Asia/Shanghai",
    "Asia/Hong_Kong",
    # Central Asia / Middle East
    "Asia/Almaty",
    "Asia/Dubai",
    "Asia/Karachi",
    # Africa
    "Africa/Nairobi",
    "Africa/Addis_Ababa",
    "Africa/Johannesburg",
    "Africa/Lagos",
    "Africa/Cairo",
    # Europe
    "Europe/London",
    "Europe/Paris",
    "Europe/Berlin",
    "Europe/Moscow",
    # Americas
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Anchorage",
    "America/Sao_Paulo",
    # Pacific / Oceania
    "Australia/Sydney",
    "Australia/Perth",
    "Pacific/Auckland",
    "Pacific/Honolulu",
    # Fallback
    "UTC",
]


def infer_from_gps(lat: float, lon: float) -> Optional[str]:
    """
    Return IANA timezone name for these coordinates, or None on failure.
    Requires the timezonefinder package.
    """
    try:
        from timezonefinder import TimezoneFinder
        tf = TimezoneFinder()
        return tf.timezone_at(lat=lat, lng=lon)
    except ImportError:
        return None
    except Exception:
        return None


def best_timezone(
    lat: Optional[float],
    lon: Optional[float],
    exif_offset: Optional[str],
) -> tuple[str, str]:
    """
    Return (iana_timezone, source_label).

    Resolution order:
      1. timezonefinder inference from GPS (most reliable)
      2. EXIF offset present — return UTC as fallback with a note
      3. UTC
    """
    if lat is not None and lon is not None:
        tz = infer_from_gps(lat, lon)
        if tz:
            return tz, "inferred from GPS"

    if exif_offset:
        # We have an offset but no IANA name — show UTC and let user correct
        return "UTC", f"EXIF offset {exif_offset} (please confirm)"

    return "UTC", "unknown — please confirm"
