# © Aditya Rao (aditya.r.rao@gmail.com)
"""
ExifService — wraps the local exiftool binary to extract EXIF metadata.

Extraction order:
  1. Locate exiftool (PATH, Homebrew, common system paths, bundled binary)
  2. Run:  exiftool -json -n <fields> <file>
  3. Parse JSON, map to PhotoMetadata
  4. Collect warnings for anything missing or ambiguous
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from models.photo_metadata import PhotoMetadata

# ---------------------------------------------------------------------------
# Fields requested from ExifTool (-n returns numeric values where possible)
# ---------------------------------------------------------------------------
_EXIF_FIELDS = [
    "-DateTimeOriginal",
    "-CreateDate",
    "-OffsetTimeOriginal",
    "-SubSecDateTimeOriginal",
    "-GPSLatitude",
    "-GPSLongitude",
    "-GPSAltitude",
    "-GPSDateTime",
    "-Make",
    "-Model",
    "-LensModel",
    "-FocalLength",
    "-ExposureTime",
    "-FNumber",
    "-ISO",
]

# ---------------------------------------------------------------------------
# ExifTool discovery
# ---------------------------------------------------------------------------

def find_exiftool() -> Optional[str]:
    """Return the path to an exiftool binary, or None if not found."""

    # 1. Check if a bundled binary lives next to this package (for future .app bundle)
    bundled = Path(sys.argv[0]).parent / "exiftool"
    if bundled.exists():
        return str(bundled)

    # 2. PATH
    found = shutil.which("exiftool")
    if found:
        return found

    # 3. Common install locations on macOS
    candidates = [
        "/usr/local/bin/exiftool",       # Intel Homebrew / manual install
        "/opt/homebrew/bin/exiftool",    # Apple Silicon Homebrew
        "/usr/bin/exiftool",
    ]
    for c in candidates:
        if Path(c).exists():
            return c

    return None


def exiftool_version() -> Optional[str]:
    """Return the exiftool version string, or None."""
    path = find_exiftool()
    if not path:
        return None
    try:
        result = subprocess.run(
            [path, "-ver"],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip() or None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Core extraction
# ---------------------------------------------------------------------------

def extract_exif(file_path: str) -> PhotoMetadata:
    """
    Extract EXIF metadata from a JPEG file via exiftool.

    Always returns a PhotoMetadata instance; warnings list describes
    any missing or problematic data.
    """
    path = Path(file_path).resolve()
    metadata = PhotoMetadata(
        file_path=str(path),
        file_name=path.name,
    )

    # --- Pre-flight checks ---
    exiftool_path = find_exiftool()
    if not exiftool_path:
        metadata.warnings.append(
            "ExifTool not found. Install with:  brew install exiftool"
        )
        return metadata

    if not path.exists():
        metadata.warnings.append(f"File not found: {path}")
        return metadata

    # --- Run ExifTool ---
    cmd = [exiftool_path, "-json", "-n"] + _EXIF_FIELDS + [str(path)]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        metadata.warnings.append("ExifTool timed out (>15 s). File may be corrupted.")
        return metadata
    except Exception as e:
        metadata.warnings.append(f"Failed to launch ExifTool: {e}")
        return metadata

    if result.returncode != 0:
        metadata.warnings.append(f"ExifTool error: {result.stderr.strip()}")
        return metadata

    # --- Parse JSON ---
    try:
        records = json.loads(result.stdout)
    except json.JSONDecodeError:
        metadata.warnings.append("Could not parse ExifTool JSON output.")
        return metadata

    if not records:
        metadata.warnings.append("ExifTool returned no data for this file.")
        return metadata

    exif = records[0]
    metadata.raw_exif = exif

    # --- Datetime ---
    metadata.date_time_original = (
        exif.get("DateTimeOriginal")
        or exif.get("SubSecDateTimeOriginal")
        or exif.get("CreateDate")
    )
    metadata.offset_time_original = exif.get("OffsetTimeOriginal")
    metadata.gps_date_time = exif.get("GPSDateTime")

    if not metadata.date_time_original:
        metadata.warnings.append(
            "No capture timestamp found in EXIF. "
            "Weather lookup will require a manual date/time."
        )

    # --- GPS ---
    lat = exif.get("GPSLatitude")
    lon = exif.get("GPSLongitude")

    if lat is not None and lon is not None:
        metadata.latitude = float(lat)
        metadata.longitude = float(lon)
    else:
        metadata.warnings.append(
            "No GPS coordinates found. "
            "Location, elevation, and weather cannot be generated automatically."
        )

    alt = exif.get("GPSAltitude")
    if alt is not None:
        metadata.gps_altitude_m = float(alt)

    # --- Camera body ---
    metadata.camera_make = _clean(exif.get("Make"))
    metadata.camera_model = _clean(exif.get("Model"))

    # --- Lens & exposure ---
    metadata.lens_model = _clean(exif.get("LensModel"))

    fl = exif.get("FocalLength")
    if fl is not None:
        metadata.focal_length = f"{fl:.0f} mm"

    exp = exif.get("ExposureTime")
    if exp is not None:
        metadata.exposure_time = _format_exposure(float(exp))

    fn = exif.get("FNumber")
    if fn is not None:
        metadata.f_number = float(fn)

    iso = exif.get("ISO")
    if iso is not None:
        metadata.iso = int(iso)

    return metadata


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean(value) -> Optional[str]:
    """Strip whitespace; return None if empty."""
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _format_exposure(seconds: float) -> str:
    """Convert a float exposure time to a readable string."""
    if seconds == 0:
        return "0s"
    if seconds >= 1:
        return f"{seconds:.1f}s"
    # Express as fraction  e.g. 1/2500s
    denom = round(1.0 / seconds)
    return f"1/{denom}s"
