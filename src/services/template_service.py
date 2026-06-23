# © Aditya Rao (aditya.r.rao@gmail.com)
"""
TemplateService — builds eBird-ready description text.

Flow
----
  1. build_context()  — assembles a flat dict of every template variable
                        from PhotoMetadata + optional location + optional weather.
                        Missing values resolve to safe fallback strings; no
                        placeholder ever becomes "None" or "{}".
  2. render()         — simple {key} substitution on a template string.
  3. generate()       — convenience: fetches template from DB, calls both above.

All three templates (default / minimal / naturalist) use the same context dict.
"""

from datetime import datetime
from typing import Optional

from models.photo_metadata import PhotoMetadata


# ---------------------------------------------------------------------------
# WMO weather code → human description
# ---------------------------------------------------------------------------

_WMO_LABELS: dict[int, str] = {
    0:  "clear sky",
    1:  "mainly clear",     2: "partly cloudy",    3: "overcast clouds",
    45: "foggy",            48: "icy fog",
    51: "light drizzle",    53: "moderate drizzle", 55: "dense drizzle",
    61: "light rain",       63: "moderate rain",    65: "heavy rain",
    71: "light snow",       73: "moderate snow",    75: "heavy snow",
    77: "snow grains",
    80: "light showers",    81: "moderate showers", 82: "violent showers",
    85: "light snow showers", 86: "heavy snow showers",
    95: "thunderstorm",     96: "thunderstorm with hail",
    99: "thunderstorm with heavy hail",
}


def wmo_label(code: Optional[int]) -> Optional[str]:
    if code is None:
        return None
    return _WMO_LABELS.get(code)


# ---------------------------------------------------------------------------
# Beaufort wind scale
# ---------------------------------------------------------------------------

def beaufort_label(kmh: Optional[float]) -> Optional[str]:
    if kmh is None:
        return None
    if kmh < 1:   return "calm"
    if kmh < 6:   return "light air"
    if kmh < 12:  return "light breeze"
    if kmh < 20:  return "gentle breeze"
    if kmh < 29:  return "moderate breeze"
    if kmh < 39:  return "fresh breeze"
    if kmh < 50:  return "strong breeze"
    if kmh < 62:  return "near gale"
    if kmh < 75:  return "gale"
    if kmh < 89:  return "severe gale"
    if kmh < 103: return "storm"
    return "violent storm"


# ---------------------------------------------------------------------------
# Wind direction degrees → cardinal
# ---------------------------------------------------------------------------

def cardinal_direction(deg: Optional[float]) -> Optional[str]:
    if deg is None:
        return None
    dirs = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    ix = round(deg / 22.5) % 16
    return dirs[ix]


# ---------------------------------------------------------------------------
# EXIF datetime parser
# ---------------------------------------------------------------------------

def parse_exif_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """
    Parse ExifTool datetime strings.
    Handles:  "2026:06:18 07:42:00"
              "2026:06:18 07:42:00.123"
              "2026-06-18T07:42:00"
    """
    if not dt_str:
        return None
    for fmt in (
        "%Y:%m:%d %H:%M:%S",
        "%Y:%m:%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(dt_str[:19], fmt[:len(fmt)])
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------

def build_context(
    metadata: PhotoMetadata,
    location: Optional[dict] = None,
    weather: Optional[dict] = None,
    custom_text: str = "",
    timezone_str: Optional[str] = None,
    show_coords: bool = True,
) -> dict:
    """
    Build the flat template variable dict.

    All values are strings — no None ever reaches the template renderer.

    show_coords=False omits exact GPS from the output (for sensitive species).
    The {coords_text} variable is the recommended way to include/exclude
    coordinates in templates; {latitude}/{longitude} remain available too.
    """
    ctx: dict = {}

    # --- Coordinates ---
    if metadata.has_gps:
        lat, lon = metadata.latitude, metadata.longitude
        lat_hem = "N" if lat >= 0 else "S"
        lon_hem = "E" if lon >= 0 else "W"
        ctx["latitude"]  = f"{abs(lat):.6f}°{lat_hem}"
        ctx["longitude"] = f"{abs(lon):.6f}°{lon_hem}"
        if show_coords:
            ctx["coords_text"] = f"at approximately {ctx['latitude']}, {ctx['longitude']}, "
        else:
            ctx["latitude"]    = ""
            ctx["longitude"]   = ""
            ctx["coords_text"] = ""
    else:
        ctx["latitude"]    = "coordinates unavailable"
        ctx["longitude"]   = "coordinates unavailable"
        ctx["coords_text"] = ""

    # --- Elevation ---
    if metadata.gps_altitude_m is not None:
        m = metadata.gps_altitude_m
        ft = m * 3.28084
        ctx["elevation"] = f"approx. {m:,.0f} m ({ft:,.0f} ft)"
    else:
        ctx["elevation"] = "elevation unavailable"

    # --- Datetime ---
    dt = parse_exif_datetime(metadata.date_time_original)
    if dt:
        ctx["local_date"]     = dt.strftime("%d %B %Y")
        ctx["local_time"]     = dt.strftime("%H:%M")
        ctx["local_datetime"] = f"{ctx['local_date']}, {ctx['local_time']}"
    else:
        ctx["local_date"]     = "date unknown"
        ctx["local_time"]     = "time unknown"
        ctx["local_datetime"] = "date/time unknown"

    # --- Timezone ---
    tz = timezone_str or metadata.offset_time_original
    ctx["timezone"] = tz if tz else "(timezone unconfirmed)"

    # --- Location (optional — M4 fills this) ---
    if location:
        ctx["nearest_place"] = location.get("nearest_place") or "nearby location"
        ctx["admin_region"]  = location.get("admin_region")  or ""
        ctx["country"]       = location.get("country")       or ""
        dist = location.get("distance_km")
        ctx["distance"]      = f"{dist:.1f} km" if dist else ""
    else:
        ctx["nearest_place"] = "location not yet resolved"
        ctx["admin_region"]  = ""
        ctx["country"]       = ""
        ctx["distance"]      = ""

    # Build a tidy "near X, Y, Z" string that skips empty parts
    place_parts = [p for p in [
        ctx["nearest_place"], ctx["admin_region"], ctx["country"]
    ] if p]
    ctx["place_full"] = ", ".join(place_parts) if place_parts else "location unknown"

    # --- Weather (optional — M5 fills this) ---
    if weather:
        temp  = weather.get("temperature_c")
        hum   = weather.get("relative_humidity")
        wind  = weather.get("wind_speed_kmh")
        wdir  = weather.get("wind_direction_deg")
        cloud = weather.get("cloud_cover_pct")
        code  = weather.get("weather_code")

        ctx["temperature_c"] = f"{temp:.0f}" if temp is not None else "—"
        ctx["temperature_f"] = f"{temp * 9/5 + 32:.0f}" if temp is not None else "—"
        ctx["humidity"]      = f"{hum:.0f}"  if hum  is not None else "—"
        ctx["wind_speed"]    = f"{wind:.0f} km/h" if wind is not None else "—"
        ctx["wind_label"]    = beaufort_label(wind) or "—"
        ctx["wind_dir"]      = cardinal_direction(wdir) or "—"
        ctx["cloud_cover"]   = f"{cloud:.0f}%" if cloud is not None else "—"
        ctx["condition"]     = wmo_label(code) or "—"

        ctx["sunrise"] = weather.get("sunrise") or "—"
        ctx["sunset"]  = weather.get("sunset")  or "—"

        # Composite extras for default template:  ", mildly cloudy conditions"
        extra_parts = []
        if wind is not None:
            extra_parts.append(f"{beaufort_label(wind)} wind from {cardinal_direction(wdir)}" if wdir else beaufort_label(wind))
        if cloud is not None:
            extra_parts.append(f"{cloud:.0f}% cloud cover")
        ctx["weather_extra"] = (", " + ", ".join(filter(None, extra_parts))) if extra_parts else ""

        # Naturalist phrase:  "cool and mildly cloudy, around 13°C with 72% humidity"
        temp_label = _temp_label(temp)
        cloud_label = _cloud_label(cloud)
        phrase_parts = []
        if temp_label and cloud_label:
            phrase_parts.append(f"{temp_label} and {cloud_label}")
        elif temp_label:
            phrase_parts.append(temp_label)
        if temp is not None:
            phrase_parts.append(f"around {temp:.0f}°C")
        if hum is not None:
            phrase_parts.append(f"{hum:.0f}% relative humidity")
        ctx["weather_phrase"] = ", ".join(phrase_parts) if phrase_parts else "conditions unknown"

        ctx["weather_summary"] = (
            f"Estimated historical weather: {ctx['condition'].capitalize()}, "
            f"{ctx['temperature_c']}°C, {ctx['humidity']}% RH, "
            f"wind {ctx['wind_label']} ({ctx['wind_speed']}) from {ctx['wind_dir']}, "
            f"{ctx['cloud_cover']} cloud cover. "
            f"Sunrise {ctx['sunrise']}, Sunset {ctx['sunset']}."
        )
    else:
        ctx["temperature_c"]   = "—"
        ctx["temperature_f"]   = "—"
        ctx["humidity"]        = "—"
        ctx["wind_speed"]      = "—"
        ctx["wind_label"]      = "—"
        ctx["wind_dir"]        = "—"
        ctx["cloud_cover"]     = "—"
        ctx["condition"]       = "—"
        ctx["sunrise"]         = "—"
        ctx["sunset"]          = "—"
        ctx["weather_extra"]   = ""
        ctx["weather_phrase"]  = "conditions unavailable"
        ctx["weather_summary"] = "Weather estimate unavailable."

    # --- Custom text ---
    ctx["custom_text"] = custom_text.strip()

    return ctx


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

def render(template_text: str, context: dict) -> str:
    """
    Fill {placeholders} in template_text from context.
    Unknown keys are left as-is so nothing crashes on a typo.
    """
    try:
        return template_text.format_map(_SafeDict(context))
    except Exception as e:
        return f"[Template render error: {e}]\n\n{template_text}"


# ---------------------------------------------------------------------------
# Convenience entry point
# ---------------------------------------------------------------------------

def generate(
    metadata: PhotoMetadata,
    template_name: str,
    db,                              # DatabaseService — passed in to avoid circular import
    location: Optional[dict] = None,
    weather:  Optional[dict] = None,
    custom_text: str = "",
    timezone_str: Optional[str] = None,
    show_coords: bool = True,
) -> tuple[str, list[str]]:
    """
    Generate a final description string plus a list of any warnings.
    Returns ("generated text", ["warning1", ...])
    """
    warnings: list[str] = []

    # Fetch template from DB
    tmpl = db.get_template(template_name) if db else None
    if tmpl is None:
        tmpl = db.get_default_template() if db else None
    if tmpl is None:
        warnings.append("No template found — using built-in fallback.")
        template_text = _FALLBACK_TEMPLATE
    else:
        template_text = tmpl["template_text"]

    # Build context with graceful fallbacks
    if not metadata.has_gps:
        warnings.append("No GPS — location and weather fields will be empty.")
    if not metadata.date_time_original:
        warnings.append("No EXIF timestamp — date/time fields will be unknown.")

    ctx = build_context(metadata, location, weather, custom_text, timezone_str, show_coords)
    text = render(template_text, ctx)
    return text, warnings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FALLBACK_TEMPLATE = (
    "Photographed at {latitude}, {longitude}, elevation {elevation}. "
    "EXIF time: {local_datetime} {timezone}.\n\n{custom_text}"
)


class _SafeDict(dict):
    """dict subclass that returns '{key}' for missing keys instead of raising."""
    def __missing__(self, key):
        return "{" + key + "}"


def _temp_label(temp_c: Optional[float]) -> Optional[str]:
    if temp_c is None:
        return None
    if temp_c < 5:   return "very cold"
    if temp_c < 12:  return "cold"
    if temp_c < 18:  return "cool"
    if temp_c < 24:  return "mild"
    if temp_c < 30:  return "warm"
    return "hot"


def _cloud_label(cloud_pct: Optional[float]) -> Optional[str]:
    if cloud_pct is None:
        return None
    if cloud_pct < 20:  return "clear"
    if cloud_pct < 50:  return "partly cloudy"
    if cloud_pct < 80:  return "mostly cloudy"
    return "overcast"
