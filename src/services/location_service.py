# © Aditya Rao (aditya.r.rao@gmail.com)
"""
LocationService — offline nearest-place lookup using GeoNames data.

First run: downloads cities500.zip + admin1CodesASCII.txt from GeoNames,
imports into the local SQLite places table (~200k rows, one-time ~30s).
All subsequent lookups are instant from SQLite + location_cache.
"""

import io
import math
import urllib.request
import zipfile
from typing import Callable, Optional

from services.db_service import DatabaseService

CITIES_URL  = "https://download.geonames.org/export/dump/cities500.zip"
ADMIN1_URL  = "https://download.geonames.org/export/dump/admin1CodesASCII.txt"
COUNTRY_URL = "https://download.geonames.org/export/dump/countryInfo.txt"

SEARCH_RADIUS_KM = 50.0
FALLBACK_RADIUS_KM = 150.0


# ---------------------------------------------------------------------------
# Haversine
# ---------------------------------------------------------------------------

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(d_lon / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(max(0.0, a)))


# ---------------------------------------------------------------------------
# LocationService
# ---------------------------------------------------------------------------

class LocationService:

    def __init__(self, db: DatabaseService):
        self._db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def places_loaded(self) -> bool:
        try:
            return self._db.places_loaded()
        except Exception:
            return False

    def lookup(self, lat: float, lon: float) -> Optional[dict]:
        """
        Return nearest place dict or None.
        Checks location_cache first; falls back to places table query.
        """
        cached = self._db.get_location_cache(lat, lon)
        if cached:
            cached["source"] = "cache"
            return cached

        result = self._query_places(lat, lon)
        if result:
            self._db.save_location_cache(lat, lon, result)
        return result

    def download_and_import(
        self,
        progress_cb: Optional[Callable[[str, float], None]] = None,
    ) -> bool:
        """
        Download GeoNames data and import into the places table.
        progress_cb(message, 0.0-1.0) called throughout.
        Returns True on success.
        """
        def prog(msg, pct):
            if progress_cb:
                progress_cb(msg, pct)

        try:
            prog("Downloading country list…", 0.02)
            countries = self._fetch_countries()

            prog("Downloading admin region names…", 0.08)
            admin1 = self._fetch_admin1()

            prog("Downloading city data (cities500.zip, ~5 MB)…", 0.15)
            rows = self._fetch_cities(countries, admin1, prog)

            prog(f"Importing {len(rows):,} places into database…", 0.85)
            chunk = 2000
            for i in range(0, len(rows), chunk):
                self._db.bulk_insert_places(rows[i:i + chunk])

            prog(f"Done — {self._db.places_count():,} places loaded.", 1.0)
            return True

        except Exception as e:
            prog(f"Download failed: {e}", -1.0)
            return False

    # ------------------------------------------------------------------
    # Internal — data fetching
    # ------------------------------------------------------------------

    def _fetch_countries(self) -> dict[str, str]:
        """Return {country_code: country_name}."""
        raw = self._http_get(COUNTRY_URL).decode("utf-8", errors="replace")
        result = {}
        for line in raw.splitlines():
            if line.startswith("#") or not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) >= 5:
                result[parts[0]] = parts[4]   # ISO2, Country name
        return result

    def _fetch_admin1(self) -> dict[str, str]:
        """Return {(country_code, admin1_code): admin1_name}."""
        raw = self._http_get(ADMIN1_URL).decode("utf-8", errors="replace")
        result = {}
        for line in raw.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                code = parts[0]   # e.g. "IN.02"
                name = parts[1]
                if "." in code:
                    cc, a1 = code.split(".", 1)
                    result[(cc, a1)] = name
        return result

    def _fetch_cities(
        self,
        countries: dict,
        admin1: dict,
        prog: Callable,
    ) -> list[dict]:
        """Download cities500.zip and parse into list of row dicts."""
        data = self._http_get(CITIES_URL)
        prog("Parsing city records…", 0.50)

        rows = []
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            fname = [n for n in zf.namelist() if n.endswith(".txt")][0]
            with zf.open(fname) as f:
                for line in io.TextIOWrapper(f, encoding="utf-8", errors="replace"):
                    parts = line.rstrip("\n").split("\t")
                    if len(parts) < 19:
                        continue
                    try:
                        cc      = parts[8]
                        a1_code = parts[10]
                        rows.append({
                            "geoname_id":   int(parts[0]),
                            "name":         parts[1],
                            "latitude":     float(parts[4]),
                            "longitude":    float(parts[5]),
                            "country_code": cc,
                            "country_name": countries.get(cc, cc),
                            "admin1_name":  admin1.get((cc, a1_code), ""),
                            "population":   int(parts[14]) if parts[14] else 0,
                            "timezone":     parts[17],
                        })
                    except (ValueError, IndexError):
                        continue
        return rows

    @staticmethod
    def _http_get(url: str) -> bytes:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "AvianPhotoMetadataAssistant/1.0"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()

    # ------------------------------------------------------------------
    # Internal — SQLite query
    # ------------------------------------------------------------------

    def _query_places(self, lat: float, lon: float) -> Optional[dict]:
        for radius_km in (SEARCH_RADIUS_KM, FALLBACK_RADIUS_KM):
            result = self._nearest_in_radius(lat, lon, radius_km)
            if result:
                return result
        return None

    def _nearest_in_radius(
        self, lat: float, lon: float, radius_km: float
    ) -> Optional[dict]:
        km_per_deg_lat = 111.0
        km_per_deg_lon = max(1.0, 111.0 * math.cos(math.radians(lat)))
        d_lat = radius_km / km_per_deg_lat
        d_lon = radius_km / km_per_deg_lon

        candidates = self._db.query_nearest_places(lat, lon, d_lat, d_lon)
        if not candidates:
            return None

        best, best_km = None, float("inf")
        for row in candidates:
            km = haversine_km(lat, lon, row["latitude"], row["longitude"])
            if km < best_km:
                best_km = km
                best = row

        if best is None:
            return None

        # Build admin / country string, skipping blanks
        region = best.get("admin1_name") or ""
        country = best.get("country_name") or best.get("country_code") or ""

        confidence = (
            "high"   if best_km < 15  else
            "medium" if best_km < 50  else
            "low"
        )

        return {
            "nearest_place": best["name"],
            "admin_region":  region,
            "country":       country,
            "distance_km":   round(best_km, 1),
            "source":        "geonames_local",
            "confidence":    confidence,
        }
