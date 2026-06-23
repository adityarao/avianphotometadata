# © Aditya Rao (aditya.r.rao@gmail.com)
"""
DatabaseService — lightweight SQLite cache layer.

Purpose
-------
This is NOT a photo archive. No photos, paths, or user history are stored.
The database is a pure service cache:

  location_cache   — maps rounded GPS coords → nearest place name
                     avoids redundant GeoNames lookups across sessions
  weather_cache    — maps rounded coords + date + timezone → Open-Meteo response
                     avoids redundant API calls; enables offline reuse
  templates        — the 3 built-in description templates (default / minimal / naturalist)
                     user can customise these in M6

DB file location:  ~/Library/Application Support/AvianPhotoMetadata/avian_cache.db
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# DB location
# ---------------------------------------------------------------------------

def _db_path() -> Path:
    app_support = Path.home() / "Library" / "Application Support" / "AvianPhotoMetadata"
    app_support.mkdir(parents=True, exist_ok=True)
    return app_support / "avian_cache.db"


# ---------------------------------------------------------------------------
# Coordinate rounding helpers
# ---------------------------------------------------------------------------

def round_location(lat: float, lon: float) -> tuple[float, float]:
    """Round to 3 dp (~100 m) for location cache key."""
    return round(lat, 3), round(lon, 3)


def round_weather(lat: float, lon: float) -> tuple[float, float]:
    """Round to 2 dp (~1 km) for weather cache key."""
    return round(lat, 2), round(lon, 2)


# ---------------------------------------------------------------------------
# Default templates
# ---------------------------------------------------------------------------

_DEFAULT_TEMPLATES = [
    {
        "name": "default",
        "is_default": 1,
        "template_text": (
            "Photographed near {nearest_place}, {admin_region}, {country} ({distance}), "
            "{coords_text}elevation {elevation}. "
            "Photographed on {local_datetime} {timezone}. "
            "Estimated historical weather: {condition}, "
            "{temperature_c}°C ({temperature_f}°F), {humidity}% humidity, "
            "{wind_label} from {wind_dir} ({wind_speed}), "
            "sunrise {sunrise}, sunset {sunset}.\n\n"
            "{custom_text}"
        ),
    },
    {
        "name": "minimal",
        "is_default": 0,
        "template_text": (
            "Photographed near {nearest_place}, {admin_region}, {country}. "
            "{coords_text}elevation {elevation}. "
            "Photographed on {local_datetime} {timezone}. "
            "Estimated weather: {temperature_c}°C, {humidity}% RH.\n\n"
            "{custom_text}"
        ),
    },
    {
        "name": "naturalist",
        "is_default": 0,
        "template_text": (
            "Photographed near {nearest_place}, {admin_region}, {country}, "
            "around {local_time} on {local_date}. "
            "The location is {coords_text}elevation {elevation}. "
            "Historical weather estimate for the time suggests {weather_phrase}.\n\n"
            "{custom_text}"
        ),
    },
]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS places (
    geoname_id   INTEGER PRIMARY KEY,
    name         TEXT    NOT NULL,
    admin1_name  TEXT,
    country_code TEXT,
    country_name TEXT,
    latitude     REAL    NOT NULL,
    longitude    REAL    NOT NULL,
    population   INTEGER,
    timezone     TEXT
);
CREATE INDEX IF NOT EXISTS idx_places_lat ON places(latitude);
CREATE INDEX IF NOT EXISTS idx_places_lon ON places(longitude);

CREATE TABLE IF NOT EXISTS location_cache (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    lat_round   REAL    NOT NULL,
    lon_round   REAL    NOT NULL,

    nearest_place   TEXT,
    admin_region    TEXT,
    country         TEXT,
    distance_km     REAL,
    source          TEXT,
    confidence      TEXT,

    created_at  TEXT NOT NULL,

    UNIQUE(lat_round, lon_round)
);

CREATE TABLE IF NOT EXISTS weather_cache (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    lat_round   REAL    NOT NULL,
    lon_round   REAL    NOT NULL,
    weather_date TEXT   NOT NULL,
    timezone    TEXT    NOT NULL,

    source              TEXT,
    matched_time        TEXT,
    temperature_c       REAL,
    relative_humidity   REAL,
    precipitation_mm    REAL,
    cloud_cover_pct     REAL,
    wind_speed_kmh      REAL,
    wind_direction_deg  REAL,
    weather_code        INTEGER,
    sunrise             TEXT,
    sunset              TEXT,
    raw_json            TEXT,
    confidence          TEXT,

    created_at  TEXT NOT NULL,

    UNIQUE(lat_round, lon_round, weather_date, timezone)
);

CREATE TABLE IF NOT EXISTS templates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    template_text TEXT NOT NULL,
    is_default  INTEGER DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""


# ---------------------------------------------------------------------------
# DatabaseService
# ---------------------------------------------------------------------------

class DatabaseService:
    """
    Thin wrapper around sqlite3. Call init() once at app start.
    All methods are synchronous (fine for a desktop JIT tool).
    """

    def __init__(self):
        self._path = _db_path()
        self._conn: Optional[sqlite3.Connection] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def init(self) -> Path:
        """Create/open the DB, apply schema, seed templates. Returns DB path."""
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._seed_templates()
        self._migrate_templates()
        return self._path

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def _conn_or_raise(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("DatabaseService.init() has not been called.")
        return self._conn

    # ------------------------------------------------------------------
    # Location cache
    # ------------------------------------------------------------------

    def get_location_cache(self, lat: float, lon: float) -> Optional[dict]:
        """Return cached location result for these coordinates, or None."""
        lat_r, lon_r = round_location(lat, lon)
        conn = self._conn_or_raise()
        row = conn.execute(
            "SELECT * FROM location_cache WHERE lat_round=? AND lon_round=?",
            (lat_r, lon_r),
        ).fetchone()
        return dict(row) if row else None

    def save_location_cache(self, lat: float, lon: float, result: dict):
        """
        Upsert a location lookup result.
        result keys: nearest_place, admin_region, country, distance_km,
                     source, confidence
        """
        lat_r, lon_r = round_location(lat, lon)
        now = _now()
        conn = self._conn_or_raise()
        conn.execute(
            """
            INSERT INTO location_cache
                (lat_round, lon_round, nearest_place, admin_region, country,
                 distance_km, source, confidence, created_at)
            VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(lat_round, lon_round) DO UPDATE SET
                nearest_place = excluded.nearest_place,
                admin_region  = excluded.admin_region,
                country       = excluded.country,
                distance_km   = excluded.distance_km,
                source        = excluded.source,
                confidence    = excluded.confidence,
                created_at    = excluded.created_at
            """,
            (
                lat_r, lon_r,
                result.get("nearest_place"),
                result.get("admin_region"),
                result.get("country"),
                result.get("distance_km"),
                result.get("source"),
                result.get("confidence"),
                now,
            ),
        )
        conn.commit()

    # ------------------------------------------------------------------
    # Weather cache
    # ------------------------------------------------------------------

    def get_weather_cache(
        self, lat: float, lon: float, date: str, tz: str
    ) -> Optional[dict]:
        """
        Return cached weather for lat/lon + date (YYYY-MM-DD) + timezone.
        Returns the full dict including raw_json, or None on miss.
        """
        lat_r, lon_r = round_weather(lat, lon)
        conn = self._conn_or_raise()
        row = conn.execute(
            """
            SELECT * FROM weather_cache
            WHERE lat_round=? AND lon_round=? AND weather_date=? AND timezone=?
            """,
            (lat_r, lon_r, date, tz),
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        # Inflate raw_json back to dict if present
        if d.get("raw_json"):
            d["raw_json"] = json.loads(d["raw_json"])
        return d

    def save_weather_cache(
        self, lat: float, lon: float, date: str, tz: str, result: dict
    ):
        """
        Upsert a weather lookup result.
        result keys: source, matched_time, temperature_c, relative_humidity,
                     precipitation_mm, cloud_cover_pct, wind_speed_kmh,
                     wind_direction_deg, weather_code, sunrise, sunset,
                     raw_json (dict), confidence
        """
        lat_r, lon_r = round_weather(lat, lon)
        now = _now()
        raw = result.get("raw_json")
        raw_str = json.dumps(raw) if isinstance(raw, dict) else raw
        conn = self._conn_or_raise()
        conn.execute(
            """
            INSERT INTO weather_cache
                (lat_round, lon_round, weather_date, timezone,
                 source, matched_time, temperature_c, relative_humidity,
                 precipitation_mm, cloud_cover_pct, wind_speed_kmh,
                 wind_direction_deg, weather_code, sunrise, sunset,
                 raw_json, confidence, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(lat_round, lon_round, weather_date, timezone) DO UPDATE SET
                source             = excluded.source,
                matched_time       = excluded.matched_time,
                temperature_c      = excluded.temperature_c,
                relative_humidity  = excluded.relative_humidity,
                precipitation_mm   = excluded.precipitation_mm,
                cloud_cover_pct    = excluded.cloud_cover_pct,
                wind_speed_kmh     = excluded.wind_speed_kmh,
                wind_direction_deg = excluded.wind_direction_deg,
                weather_code       = excluded.weather_code,
                sunrise            = excluded.sunrise,
                sunset             = excluded.sunset,
                raw_json           = excluded.raw_json,
                confidence         = excluded.confidence,
                created_at         = excluded.created_at
            """,
            (
                lat_r, lon_r, date, tz,
                result.get("source"),
                result.get("matched_time"),
                result.get("temperature_c"),
                result.get("relative_humidity"),
                result.get("precipitation_mm"),
                result.get("cloud_cover_pct"),
                result.get("wind_speed_kmh"),
                result.get("wind_direction_deg"),
                result.get("weather_code"),
                result.get("sunrise"),
                result.get("sunset"),
                raw_str,
                result.get("confidence"),
                now,
            ),
        )
        conn.commit()

    # ------------------------------------------------------------------
    # Templates
    # ------------------------------------------------------------------

    def get_all_templates(self) -> list[dict]:
        conn = self._conn_or_raise()
        rows = conn.execute(
            "SELECT * FROM templates ORDER BY is_default DESC, name"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_template(self, name: str) -> Optional[dict]:
        conn = self._conn_or_raise()
        row = conn.execute(
            "SELECT * FROM templates WHERE name=?", (name,)
        ).fetchone()
        return dict(row) if row else None

    def get_default_template(self) -> Optional[dict]:
        conn = self._conn_or_raise()
        row = conn.execute(
            "SELECT * FROM templates WHERE is_default=1 LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def save_template(self, name: str, text: str, is_default: bool = False):
        now = _now()
        conn = self._conn_or_raise()
        conn.execute(
            """
            INSERT INTO templates (name, template_text, is_default, created_at, updated_at)
            VALUES (?,?,?,?,?)
            ON CONFLICT(name) DO UPDATE SET
                template_text = excluded.template_text,
                is_default    = excluded.is_default,
                updated_at    = excluded.updated_at
            """,
            (name, text, int(is_default), now, now),
        )
        conn.commit()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _migrate_templates(self):
        """Force-update built-in templates to the latest wording."""
        conn = self._conn_or_raise()
        now  = _now()
        for t in _DEFAULT_TEMPLATES:
            row = conn.execute(
                "SELECT template_text FROM templates WHERE name=?", (t["name"],)
            ).fetchone()
            if row and row[0] != t["template_text"]:
                conn.execute(
                    "UPDATE templates SET template_text=?, updated_at=? WHERE name=?",
                    (t["template_text"], now, t["name"]),
                )
        conn.commit()

    def _seed_templates(self):
        """Insert default templates if they don't exist yet."""
        conn = self._conn_or_raise()
        now = _now()
        for t in _DEFAULT_TEMPLATES:
            conn.execute(
                """
                INSERT OR IGNORE INTO templates
                    (name, template_text, is_default, created_at, updated_at)
                VALUES (?,?,?,?,?)
                """,
                (t["name"], t["template_text"], t["is_default"], now, now),
            )
        conn.commit()

    # ------------------------------------------------------------------
    # Places (GeoNames data)
    # ------------------------------------------------------------------

    def places_loaded(self) -> bool:
        conn = self._conn_or_raise()
        count = conn.execute("SELECT COUNT(*) FROM places").fetchone()[0]
        return count > 0

    def bulk_insert_places(self, rows: list[dict]):
        """
        Bulk-insert GeoNames place rows.
        Each dict: geoname_id, name, admin1_name, country_code,
                   country_name, latitude, longitude, population, timezone
        """
        conn = self._conn_or_raise()
        conn.executemany(
            """
            INSERT OR IGNORE INTO places
                (geoname_id, name, admin1_name, country_code, country_name,
                 latitude, longitude, population, timezone)
            VALUES (:geoname_id, :name, :admin1_name, :country_code, :country_name,
                    :latitude, :longitude, :population, :timezone)
            """,
            rows,
        )
        conn.commit()

    def query_nearest_places(
        self,
        lat: float,
        lon: float,
        lat_delta: float,
        lon_delta: float,
    ) -> list:
        """
        Return all places within the bounding box as a list of Row objects.
        Caller is responsible for Haversine filtering.
        """
        conn = self._conn_or_raise()
        rows = conn.execute(
            """
            SELECT name, admin1_name, country_code, country_name,
                   latitude, longitude, population
            FROM places
            WHERE latitude  BETWEEN ? AND ?
              AND longitude BETWEEN ? AND ?
            ORDER BY population DESC
            """,
            (lat - lat_delta, lat + lat_delta, lon - lon_delta, lon + lon_delta),
        ).fetchall()
        return [dict(r) for r in rows]

    def places_count(self) -> int:
        conn = self._conn_or_raise()
        return conn.execute("SELECT COUNT(*) FROM places").fetchone()[0]

    # ------------------------------------------------------------------

    def cache_stats(self) -> dict:
        """Return row counts for each cache table — useful for debug display."""
        conn = self._conn_or_raise()
        return {
            "location_cache": conn.execute(
                "SELECT COUNT(*) FROM location_cache"
            ).fetchone()[0],
            "weather_cache": conn.execute(
                "SELECT COUNT(*) FROM weather_cache"
            ).fetchone()[0],
            "templates": conn.execute(
                "SELECT COUNT(*) FROM templates"
            ).fetchone()[0],
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
