# © Aditya Rao (aditya.r.rao@gmail.com)
"""
avianexif — CLI companion for Avian Photo Metadata Assistant.

Generates eBird-ready descriptions from one or more bird photos,
reusing all the same services as the GUI (location, weather, templates).

Usage examples
--------------
  avianexif -f photo.jpg
  avianexif -f *.jpg -t m
  avianexif -f '*.jpg' -t n --coords
  avianexif -f DSC001.jpg -t d -c "Seen at dawn in mixed forest"
  avianexif -f *.jpg -t d > all_notes.txt
  avianexif -f *.jpg --no-weather --no-separator | pbcopy

Flags
-----
  -f / --file      One or more files or a glob pattern (e.g. *.jpg).
                   Glob is expanded in the CURRENT DIRECTORY only — not recursive.
  -t / --template  d = default (full detail, default)
                   m = minimal
                   n = naturalist
  -c / --custom    Custom field notes appended to every description.
  --coords         Include exact GPS coordinates (hidden by default).
  --no-weather     Skip Open-Meteo lookup (faster, fully offline).
  --no-separator   Suppress filename headers — useful when piping a
                   single file or when you want raw output only.

Exit codes
----------
  0  All files processed successfully (warnings may still appear on stderr)
  1  One or more files failed
"""

import argparse
import glob as glob_module
import os
import sys

# Ensure src/ is on the path regardless of where the script is called from
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.db_service import DatabaseService
from services.exif_service import extract_exif
from services.location_service import LocationService
from services.weather_service import WeatherService
from services.template_service import generate as generate_description
from services.timezone_service import best_timezone

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEMPLATE_MAP = {"d": "default", "m": "minimal", "n": "naturalist"}
SEPARATOR = "─" * 64


# ---------------------------------------------------------------------------
# File resolution
# ---------------------------------------------------------------------------

def resolve_files(patterns: list) -> list:
    """
    Expand glob patterns into a sorted list of file paths.
    Operates in the CURRENT WORKING DIRECTORY — not recursive.

    Handles both shell-expanded args (avianexif -f *.jpg) and
    quoted patterns (avianexif -f '*.jpg') transparently.
    """
    files = []
    for pattern in patterns:
        matches = sorted(glob_module.glob(pattern))
        if matches:
            files.extend(matches)
        elif os.path.exists(pattern):
            # Literal path that doesn't need globbing
            files.append(pattern)
        else:
            print(f"[warn] No files matched: {pattern}", file=sys.stderr)
    return files


# ---------------------------------------------------------------------------
# Single-file processor
# ---------------------------------------------------------------------------

def process_file(path, db, location_svc, weather_svc,
                 template_key, custom_text, show_coords):
    """
    Run the full pipeline for one file.
    Returns (description_text, warnings_list).
    All exceptions are allowed to propagate — caller handles them.
    """
    meta = extract_exif(path)
    warnings = list(meta.warnings)

    location = None
    tz_str   = None

    if meta.has_gps:
        if location_svc.places_loaded():
            location = location_svc.lookup(meta.latitude, meta.longitude)
            tz_str, _ = best_timezone(
                meta.latitude, meta.longitude, meta.offset_time_original
            )
        else:
            warnings.append(
                "GeoNames place data not downloaded yet — "
                "launch the GUI app once to set it up, then retry."
            )

    weather = None
    if weather_svc and meta.has_gps and meta.date_time_original:
        weather, err = weather_svc.lookup(
            meta.latitude, meta.longitude,
            meta.date_time_original,
            tz_str or "auto",
        )
        if err:
            warnings.append(f"Weather unavailable: {err}")

    text, gen_warnings = generate_description(
        metadata=meta,
        template_name=TEMPLATE_MAP[template_key],
        db=db,
        location=location,
        weather=weather,
        custom_text=custom_text,
        timezone_str=tz_str,
        show_coords=show_coords,
    )
    warnings.extend(gen_warnings)
    return text, warnings


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        prog="avianexif",
        description="Generate eBird-ready description(s) from bird photo(s).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
template choices:
  d  default    full detail — condition, °C/°F, wind, sunrise/sunset, distance
  m  minimal    compact — place, elevation, date, temperature, humidity
  n  naturalist prose style — weather phrase, no raw numbers

examples:
  avianexif -f photo.jpg
  avianexif -f *.jpg -t m
  avianexif -f '*.JPG' -t n --coords
  avianexif -f DSC001.jpg -t d -c "Seen at dawn in mixed forest"
  avianexif -f *.jpg -t d > all_notes.txt
        """,
    )

    parser.add_argument(
        "-f", "--file",
        nargs="+", required=True, dest="files", metavar="FILE",
        help="File(s) or glob pattern, e.g. *.jpg  (current directory, non-recursive)",
    )
    parser.add_argument(
        "-t", "--template",
        default="d", choices=["d", "m", "n"],
        help="d=default  m=minimal  n=naturalist  (default: d)",
    )
    parser.add_argument(
        "-c", "--custom",
        default="", metavar="TEXT",
        help="Custom field notes appended to the description",
    )
    parser.add_argument(
        "--coords",
        action="store_true",
        help="Include exact GPS coordinates (hidden by default)",
    )
    parser.add_argument(
        "--no-weather",
        action="store_true",
        help="Skip weather lookup — faster, fully offline",
    )
    parser.add_argument(
        "--no-separator",
        action="store_true",
        help="Suppress filename headers between multiple files",
    )

    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Resolve files
    # ------------------------------------------------------------------
    files = resolve_files(args.files)
    if not files:
        print("[error] No matching files found.", file=sys.stderr)
        sys.exit(1)

    # ------------------------------------------------------------------
    # Initialise services (shared across all files in one run)
    # ------------------------------------------------------------------
    db = DatabaseService()
    db.init()
    location_svc = LocationService(db)
    weather_svc  = None if args.no_weather else WeatherService(db)

    multi     = len(files) > 1
    exit_code = 0

    for i, path in enumerate(files):
        # Print separator / filename header for multi-file runs
        if multi and not args.no_separator:
            if i > 0:
                print()
            print(SEPARATOR)
            print(f"  {os.path.basename(path)}")
            print(SEPARATOR)

        try:
            text, warnings = process_file(
                path, db, location_svc, weather_svc,
                args.template, args.custom, args.coords,
            )
            for w in warnings:
                print(f"[warn] {w}", file=sys.stderr)
            print(text)

        except Exception as exc:
            print(f"[error] {os.path.basename(path)}: {exc}", file=sys.stderr)
            exit_code = 1

    db.close()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
