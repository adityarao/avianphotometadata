# Avian Photo Metadata Assistant — Design & Architecture

> © Aditya Rao (aditya.r.rao@gmail.com)
> Last updated: June 2026 (reflects M1–M6 as-built implementation)

---

## 1. Purpose

A simple, efficient, offline-first Mac desktop application for bird and wildlife photographers. It accepts a JPEG photograph, extracts EXIF metadata, enriches the location with geographic and estimated historical weather context, and generates clean text ready to paste into the eBird / Macaulay Library photo description field.

The application prioritises trust, editability, speed, and privacy over complexity.

---

## 2. Product Name

**Avian Photo Metadata Assistant**

---

## 3. Primary User

A wildlife / bird photographer who wants to generate accurate, copy-ready field context for uploaded bird photographs.

Typical usage:
1. Select a JPEG in the app.
2. App extracts EXIF date, time, GPS coordinates, altitude, camera, and lens details.
3. App identifies nearest place / town / region (offline, GeoNames data).
4. App infers IANA timezone from GPS coordinates (offline, timezonefinder).
5. App fetches estimated historical weather for the photo location and time (Open-Meteo).
6. User confirms timezone and adds custom text.
7. App generates final description from a chosen template.
8. User copies the text into eBird / Macaulay Library.

---

## 4. Core Principles

### 4.1 JIT (Just-in-Time) — No photo storage
The app does **not** store photo files, paths, or history. It processes one photo at a time and holds nothing after the window closes. Only service infrastructure is persisted: location cache, weather cache, and templates.

### 4.2 Offline-first
- EXIF extraction: fully offline (ExifTool subprocess)
- Location lookup: fully offline (local GeoNames SQLite)
- Timezone inference: fully offline (timezonefinder library)
- Weather: requires internet on first request; cached for reuse

### 4.3 Never overclaim
The app clearly labels:
- estimated historical weather (not actual field measurement)
- inferred timezone (user can override)
- nearest named place (distance shown)
- unavailable / missing fields shown as "—" not "null"

### 4.4 GPS privacy
Exact GPS coordinates are **hidden by default**. A checkbox labelled "Include exact GPS coords" lets the user opt in per-photo. This protects sensitive species locations when the description is posted publicly.

### 4.5 Local privacy
Images stay on the user's Mac. Only latitude, longitude, and timestamp are sent to Open-Meteo for weather enrichment. No photos or descriptions are uploaded.

---

## 5. Technology Stack (as built)

| Layer | Technology |
|---|---|
| Language | Python 3.12+ |
| UI framework | customtkinter ≥ 5.2 (dark theme, Mac-native feel) |
| Image preview | Pillow ≥ 10.0 |
| EXIF extraction | ExifTool (subprocess, JSON output) |
| Database / cache | SQLite via stdlib `sqlite3` |
| Location data | GeoNames `cities500.zip` (≈200k places, downloaded once) |
| Timezone inference | timezonefinder ≥ 6.2 (offline polygon lookup) |
| Weather API | Open-Meteo Historical Archive (`archive-api.open-meteo.com`) |
| Dependency isolation | Python virtualenv (`.venv/`) |
| Launcher | `run.sh` — probes for Python with Tk, creates venv, installs deps |

### Rate limits (external APIs)

| Service | Limit | Notes |
|---|---|---|
| Open-Meteo Historical Archive | ~10,000 requests/day (free tier) | Results cached per location+date+tz |
| GeoNames download | One-time bulk download | `cities500.zip` ~30 MB; no per-query calls |

---

## 6. External Dependencies

### ExifTool
- Installed via `brew install exiftool`
- Called as a subprocess: `exiftool -json -n <fields> <file>`
- Extracted fields: `DateTimeOriginal`, `OffsetTimeOriginal`, `GPSDateTime`, `GPSLatitude`, `GPSLongitude`, `GPSAltitude`, `Make`, `Model`, `LensModel`, `FocalLength`, `ExposureTime`, `FNumber`, `ISO`

### GeoNames cities500.zip
- Downloaded once on first run to `~/Library/Application Support/AvianPhotoMetadata/`
- Also downloads `admin1CodesASCII.txt` and `countryInfo.txt` for region/country names
- Imported into local SQLite `places` table (~200k rows)
- Lookup uses bounding-box pre-filter + Haversine exact distance
- Search radius: 50 km, expanding to 150 km if no result

### Open-Meteo Historical Weather Archive
- Endpoint: `https://archive-api.open-meteo.com/v1/archive`
- Always passes `timezone=auto` (IANA name inferred server-side from coordinates)
- Fetches hourly: `temperature_2m`, `relative_humidity_2m`, `precipitation`, `cloud_cover`, `wind_speed_10m`, `wind_direction_10m`, `weather_code`, `sunrise`, `sunset`
- Matches photo timestamp to nearest hourly row

### timezonefinder
- Offline polygon-based IANA timezone lookup from GPS coordinates
- Used to infer e.g. `Asia/Kolkata` from lat/lon without any network call
- Falls back gracefully if coordinates are missing

---

## 7. Functional Requirements

### 7.1 Photo input
- Single JPEG / RAW file selection via file picker
- Accepted types: `.jpg`, `.jpeg`, `.JPG`, `.JPEG` (and all image types via "All files")
- Graceful handling of missing EXIF, missing GPS, missing timestamp

### 7.2 EXIF extraction
ExifTool is called with `-json -n` for decimal GPS values. Fields extracted into a `PhotoMetadata` dataclass:

| Field | Fallback |
|---|---|
| `DateTimeOriginal` | Warning shown |
| `OffsetTimeOriginal` | Empty; timezone shown as "unconfirmed" |
| `GPSLatitude` / `GPSLongitude` | Location/weather skipped |
| `GPSAltitude` | Shown as "—" |
| `Make` / `Model` | Shown as "—" |
| `LensModel`, `FocalLength`, `ExposureTime`, `FNumber`, `ISO` | Shown as "—" |

### 7.3 Timezone handling
Resolution order:

1. **timezonefinder** inference from GPS coordinates → IANA name (e.g. `Asia/Kolkata`)
2. EXIF `OffsetTimeOriginal` present but no GPS → UTC shown with prompt to confirm
3. No GPS, no offset → UTC, user asked to select from dropdown

The UI shows a **"Local Timezone"** ComboBox in the Date & Time panel with 35 pre-loaded common birding timezones worldwide. The user can type any IANA name. Changing the timezone immediately re-runs the weather lookup and regenerates the description.

### 7.4 Location lookup (offline)
- Input: latitude, longitude
- Pre-filter: bounding box ±0.5° → ±1.5°
- Exact ranking: Haversine distance, tie-broken by population
- Result fields: `nearest_place`, `admin_region`, `country`, `distance_km`, `source`, `confidence`
- Cache key: coordinates rounded to 3 d.p. (~100 m)

### 7.5 Elevation
- Source: EXIF `GPSAltitude` only (v1)
- Displayed in both metres and feet: `approx. 1,720 m (5,643 ft)`
- No "EXIF" label in the generated text

### 7.6 Weather lookup (Open-Meteo)
- Input: lat, lon, date, `timezone=auto`
- Matches nearest hourly row to photo's local hour
- Cache key: coordinates rounded to 2 d.p. (~1 km) + date + timezone string
- A **↻ Refresh** button in the Weather panel header re-triggers the lookup with the current confirmed timezone

### 7.7 Custom text
Free-form multi-line text box. Placeholder hint: `e.g. Seen foraging quietly in the canopy. Active calling at dawn.` The placeholder is stripped before generating the description.

### 7.8 Description generation
Three built-in templates. The selected template **auto-regenerates** the description immediately when switched.

#### Default template (full detail)
```
Photographed near {nearest_place}, {admin_region}, {country} ({distance}),
{coords_text}elevation {elevation}.
Photographed on {local_datetime} {timezone}.
Estimated historical weather: {condition},
{temperature_c}°C ({temperature_f}°F), {humidity}% humidity,
{wind_label} from {wind_dir} ({wind_speed}),
sunrise {sunrise}, sunset {sunset}.

{custom_text}
```

#### Minimal template
```
Photographed near {nearest_place}, {admin_region}, {country}.
{coords_text}elevation {elevation}.
Photographed on {local_datetime} {timezone}.
Estimated weather: {temperature_c}°C, {humidity}% RH.

{custom_text}
```

#### Naturalist template
```
Photographed near {nearest_place}, {admin_region}, {country},
around {local_time} on {local_date}.
The location is {coords_text}elevation {elevation}.
Historical weather estimate for the time suggests {weather_phrase}.

{custom_text}
```

**GPS privacy:** when the "Include exact GPS coords" checkbox is unchecked (default), `{coords_text}` renders as an empty string — coordinates are silently omitted, no "(exact coordinates withheld)" text appears.

### 7.9 Copy to clipboard
The **Copy to Clipboard** button:
- Disables itself and shows "✅ Copied!" for 2.5 seconds
- Then resets to normal
- Prevents accidental double-copy

---

## 8. Data Model (as built — JIT design)

The app uses SQLite as a **pure service cache** — no photo history, no user records. Three tables only:

### `places` — GeoNames data (imported once)
```sql
CREATE TABLE places (
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
CREATE INDEX idx_places_lat ON places(latitude);
CREATE INDEX idx_places_lon ON places(longitude);
```

### `location_cache` — avoids repeated GeoNames lookups
```sql
CREATE TABLE location_cache (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    lat_round    REAL    NOT NULL,
    lon_round    REAL    NOT NULL,
    nearest_place TEXT,
    admin_region  TEXT,
    country       TEXT,
    distance_km   REAL,
    source        TEXT,
    confidence    TEXT,
    created_at    TEXT    NOT NULL,
    UNIQUE(lat_round, lon_round)
);
```

### `weather_cache` — avoids repeated Open-Meteo calls
```sql
CREATE TABLE weather_cache (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    lat_round          REAL    NOT NULL,
    lon_round          REAL    NOT NULL,
    weather_date       TEXT    NOT NULL,
    timezone           TEXT    NOT NULL,
    source             TEXT,
    matched_time       TEXT,
    temperature_c      REAL,
    relative_humidity  REAL,
    precipitation_mm   REAL,
    cloud_cover_pct    REAL,
    wind_speed_kmh     REAL,
    wind_direction_deg REAL,
    weather_code       INTEGER,
    sunrise            TEXT,
    sunset             TEXT,
    raw_json           TEXT,
    confidence         TEXT,
    created_at         TEXT    NOT NULL,
    UNIQUE(lat_round, lon_round, weather_date, timezone)
);
```

### `templates` — built-in and user-customisable templates
```sql
CREATE TABLE templates (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL UNIQUE,
    template_text TEXT    NOT NULL,
    is_default    INTEGER DEFAULT 0,
    created_at    TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL
);
```

**Template migration:** `DatabaseService._migrate_templates()` force-updates built-in template wording on every app launch, so existing databases pick up template changes without manual intervention.

**DB location:** `~/Library/Application Support/AvianPhotoMetadata/avian_cache.db`

---

## 9. Cache Strategy

| Cache | Key rounding | Purpose |
|---|---|---|
| `location_cache` | 3 d.p. (~100 m) | Nearest place name |
| `weather_cache` | 2 d.p. (~1 km) + date + tz | Historical weather by day |

Cache is checked first on every lookup. On a hit, the result is used immediately and no network/disk call is made.

---

## 10. Folder Structure (as built)

```
Avian Image Geo and Description Generator/
├── run.sh                          # Launcher: venv setup, dep install, launch
├── requirements.txt                # customtkinter, Pillow, timezonefinder
├── avian_photo_metadata_app_design.md  # This file
│
└── src/
    ├── main.py                     # Entry point; wires services → MainWindow
    │
    ├── models/
    │   └── photo_metadata.py       # PhotoMetadata dataclass + display helpers
    │
    ├── services/
    │   ├── db_service.py           # SQLite cache layer; template seeding/migration
    │   ├── exif_service.py         # ExifTool subprocess wrapper
    │   ├── location_service.py     # GeoNames offline lookup + download
    │   ├── weather_service.py      # Open-Meteo historical archive API
    │   ├── template_service.py     # Context builder + template renderer
    │   └── timezone_service.py     # timezonefinder wrapper; COMMON_TIMEZONES list
    │
    └── ui/
        └── main_window.py          # Main customtkinter window (all panels)
```

---

## 11. Application Flow

```
User selects JPEG
        │
        ▼
ExifService.extract_exif()
  → PhotoMetadata dataclass
        │
        ├─ has_gps?
        │      │
        │      ▼
        │  LocationService.lookup()  [background thread]
        │    → GeoNames offline DB
        │    → location_cache (upsert)
        │      │
        │      ▼
        │  TimezoneService.best_timezone()
        │    → timezonefinder offline inference
        │    → populate timezone ComboBox
        │      │
        │      ▼
        │  WeatherService.lookup()  [background thread]
        │    → weather_cache check
        │    → Open-Meteo API if cache miss
        │    → weather_cache (upsert)
        │
        ▼
MainWindow updates all panels
        │
User optionally:
  - changes timezone → re-runs weather + regenerates
  - switches template → auto-regenerates
  - ticks GPS coords checkbox → regenerates
  - clicks ↻ Refresh → re-runs weather + regenerates
        │
        ▼
User adds custom notes text
        │
        ▼
[Generate Description] → TemplateService.generate()
        │
        ▼
[Copy to Clipboard] → OS clipboard
```

---

## 12. Service Architecture

### ExifService (`exif_service.py`)
- `find_exiftool()` — probes PATH, Homebrew locations, bundled binary
- `extract_exif(path)` → `PhotoMetadata`
- `exiftool_version()` → version string for header badge
- Runs `exiftool -json -n <fields> <file>` via subprocess

### LocationService (`location_service.py`)
- `download_and_import(progress_cb)` — first-run GeoNames download with progress callback
- `lookup(lat, lon)` → result dict or None
- `places_loaded()` → bool
- Bounding-box pre-filter → Haversine exact ranking → cache upsert

### WeatherService (`weather_service.py`)
- `lookup(lat, lon, dt_str, tz)` → `(result_dict, error_str)`
- Always passes `timezone=auto` to API (Open-Meteo requires IANA names)
- `_pick_hour()` — finds hourly row nearest to photo's local hour
- WMO weather codes → human labels
- Beaufort scale: wind speed km/h → descriptive label
- Cardinal direction: wind degrees → N/NE/E/SE/S/SW/W/NW etc.

### TimezoneService (`timezone_service.py`)
- `infer_from_gps(lat, lon)` → IANA name or None
- `best_timezone(lat, lon, exif_offset)` → `(iana_name, source_label)`
- `COMMON_TIMEZONES` — 35-entry list of worldwide birding timezones for UI dropdown

### TemplateService (`template_service.py`)
- `build_context(metadata, location, weather, custom_text, timezone_str, show_coords)` → flat dict
- `render(template_text, context)` → filled string (uses `_SafeDict` — unknown keys left as-is)
- `generate(...)` → `(text, warnings_list)`
- Converts: WMO code → condition label, km/h → Beaufort, degrees → cardinal
- `{coords_text}` = `"at approximately {lat}, {lon}, "` when shown, or `""` when hidden

### DatabaseService (`db_service.py`)
- `init()` — creates DB, applies schema, seeds + migrates templates
- `get_location_cache / save_location_cache`
- `get_weather_cache / save_weather_cache`
- `get_all_templates / get_template / save_template`
- `bulk_insert_places / query_nearest_places`

---

## 13. UI Layout

```
┌──────────────────────────────────────────────────────────────────┐
│  🦅  Avian Photo Metadata Assistant      ExifTool 13.x ✓  Cache: 4 loc 2 wx │
├──────────────────────────────────────────────────────────────────┤
│  [ Choose Photo ]   /path/to/photo.jpg                           │
├────────────────────┬─────────────────────────────────────────────┤
│  Photo thumbnail   │  📅 Date & Time                             │
│  300×300 px        │      Date / Time · Timezone Offset          │
│                    │      GPS DateTime                            │
│  1200×800 px       │      Local Timezone  [Asia/Kolkata ▾]       │
│  2.4 MB            │                      (inferred from GPS)    │
│                    │  📍 GPS Location                            │
│  GeoNames          │      Coordinates · Altitude                 │
│  progress bar      │                                             │
│  (first run only)  │  🗺️  Nearest Place                         │
│                    │      Place · Region · Country · Distance    │
│                    │                                             │
│                    │  🌤️  Weather (estimated historical) [↻ Refresh] │
│                    │      Condition · Temperature · Wind          │
│                    │      Cloud Cover · Humidity · Sunrise/Sunset │
│                    │                                             │
│                    │  📷 Camera & Lens                           │
│                    │      Camera · Lens · Focal Length           │
│                    │      Exposure · ISO                         │
│                    │                                             │
│                    │  📝 Description                             │
│                    │      Template [default ▾]  ☐ Include GPS    │
│                    │      [Custom notes textbox]                 │
│                    │      [⚡ Generate Description]              │
│                    │      [Generated text — editable]            │
│                    │      [📋 Copy to Clipboard]  ✅ Copied!     │
├────────────────────┴─────────────────────────────────────────────┤
│  ✅ EXIF extracted successfully  · Weather: Open-Meteo CC BY 4.0 · GeoNames CC BY 4.0 │
└──────────────────────────────────────────────────────────────────┘
```

---

## 14. Template Variables Reference

All variables available in any template:

| Variable | Example value |
|---|---|
| `{nearest_place}` | `Dachigam` |
| `{admin_region}` | `Jammu & Kashmir` |
| `{country}` | `India` |
| `{distance}` | `2.4 km` |
| `{place_full}` | `Dachigam, Jammu & Kashmir, India` |
| `{coords_text}` | `at approximately 34.1°N, 74.9°E, ` or `""` |
| `{latitude}` | `34.153247°N` or `""` if hidden |
| `{longitude}` | `74.879921°E` or `""` if hidden |
| `{elevation}` | `approx. 1,720 m (5,643 ft)` |
| `{local_date}` | `18 June 2026` |
| `{local_time}` | `07:42` |
| `{local_datetime}` | `18 June 2026, 07:42` |
| `{timezone}` | `Asia/Kolkata` |
| `{condition}` | `partly cloudy` |
| `{temperature_c}` | `14` |
| `{temperature_f}` | `57` |
| `{humidity}` | `73` |
| `{wind_speed}` | `18 km/h` |
| `{wind_label}` | `gentle breeze` |
| `{wind_dir}` | `SE` |
| `{cloud_cover}` | `35%` |
| `{sunrise}` | `6:34 am` |
| `{sunset}` | `7:22 pm` |
| `{weather_extra}` | `, gentle breeze wind from SE, 35% cloud cover` |
| `{weather_phrase}` | `cool and partly cloudy, around 14°C with 73% relative humidity` |
| `{weather_summary}` | Full one-line weather summary |
| `{custom_text}` | User-entered notes |

---

## 15. Example Outputs

### Default template (GPS hidden)
```
Photographed near Dachigam, Jammu & Kashmir, India (2.4 km), elevation approx. 1,720 m (5,643 ft).
Photographed on 18 June 2026, 07:42 Asia/Kolkata.
Estimated historical weather: partly cloudy, 14°C (57°F), 73% humidity,
gentle breeze from SE (18 km/h), sunrise 6:34 am, sunset 7:22 pm.

Seen at dawn foraging in the mixed conifer canopy.
```

### Default template (GPS shown)
```
Photographed near Dachigam, Jammu & Kashmir, India (2.4 km), at approximately 34.153247°N, 74.879921°E,
elevation approx. 1,720 m (5,643 ft).
Photographed on 18 June 2026, 07:42 Asia/Kolkata.
Estimated historical weather: partly cloudy, 14°C (57°F), 73% humidity,
gentle breeze from SE (18 km/h), sunrise 6:34 am, sunset 7:22 pm.

Seen at dawn foraging in the mixed conifer canopy.
```

### Minimal template
```
Photographed near Dachigam, Jammu & Kashmir, India. elevation approx. 1,720 m (5,643 ft).
Photographed on 18 June 2026, 07:42 Asia/Kolkata.
Estimated weather: 14°C, 73% RH.

Seen at dawn.
```

### Naturalist template
```
Photographed near Dachigam, Jammu & Kashmir, India, around 07:42 on 18 June 2026.
The location is elevation approx. 1,720 m (5,643 ft).
Historical weather estimate for the time suggests cool and partly cloudy, around 14°C with 73% relative humidity.

Seen at dawn.
```

---

## 16. Error Handling

| Condition | UI treatment |
|---|---|
| No GPS in EXIF | ⚠️ warning bar; location/weather panels show "—" |
| No timestamp in EXIF | ⚠️ warning; date/time fields show "—" |
| ExifTool not installed | Header badge: "ExifTool not found — brew install exiftool" |
| GeoNames not yet downloaded | Progress bar in left panel (background thread) |
| Open-Meteo API error | Weather panel clears; warning bar shows exact API error message |
| Timezone ambiguous | Timezone ComboBox shown in amber with prompt to confirm |
| Missing template placeholder | `_SafeDict` leaves `{unknown_key}` literally — no crash |

---

## 17. Privacy & Data Handling

- Images never leave the user's machine
- Only lat/lon + date are sent to Open-Meteo
- GPS coordinates hidden from generated text by default
- No photo paths, filenames, or content stored in DB
- DB contains only coordinate hashes + cached API responses
- User can delete `~/Library/Application Support/AvianPhotoMetadata/` to wipe all caches

---

## 18. Build Milestones (all completed)

### M1 — EXIF Prototype ✅
- File picker, ExifTool subprocess, PhotoMetadata dataclass, basic UI panels

### M2 — Service Cache Layer ✅
- SQLite DB, JIT design (no photo storage), location_cache + weather_cache + templates tables, cache round-trip

### M3 — Description Generator ✅
- TemplateService, 3 built-in templates, custom notes box, generate + copy flow

### M4 — Location Lookup ✅
- GeoNames first-run download with progress bar, offline Haversine lookup, location panel, background threading

### M5 — Weather Lookup ✅
- Open-Meteo Historical Archive API, WMO labels, Beaufort scale, cardinal direction, weather panel, `timezone=auto` fix

### M6 — MVP Polish ✅
- timezonefinder timezone inference from GPS
- Editable timezone ComboBox (35 common birding timezones)
- Changing timezone re-triggers weather + regenerates description
- ↻ Refresh Weather button
- Template dropdown auto-regenerates on switch
- GPS coords checkbox wired to auto-regenerate
- Copy button disables briefly after click (prevents double-copy)
- Window title shows current filename
- Attribution footer: Open-Meteo CC BY 4.0 · GeoNames CC BY 4.0
- Default template enhanced: °F, condition, wind, sunrise/sunset, distance

---

## 19. Setup & Running

### Prerequisites
```bash
brew install exiftool
brew install python@3.12   # or 3.13; must have Tk support
```

### First run
```bash
cd "Avian Image Geo and Description Generator"
./run.sh
```

`run.sh` will:
1. Find a Python with working `_tkinter`
2. Create `.venv/` if absent
3. Install `customtkinter`, `Pillow`, `timezonefinder`
4. Launch the app

On first launch, GeoNames place data is downloaded and imported in the background (~30–60 s).

---

## 20. Phase 2 Ideas

- Batch photo import (queue processing)
- Trip profiles (default timezone, custom text snippet per trip)
- Template editor in UI
- CSV / Markdown export
- Offline elevation lookup (SRTM tiles)
- Map preview panel
- Species name + habitat field
- eBird checklist URL field
- Saved phrase snippets ("Seen during early morning birding…")
- Drag-and-drop file input

## 21. Phase 3 Ideas

- Mac menu bar utility
- Lightroom export plugin
- Apple Photos integration
- Automatic trip grouping by date/location
- RAW file support (NEF, ARW, CR3, DNG)
- AI-assisted species verification
- Direct eBird / Macaulay Library upload

---

## 22. Attributions

| Data source | License | Usage |
|---|---|---|
| Open-Meteo Historical Archive | CC BY 4.0 | Estimated historical weather |
| GeoNames `cities500.zip` | CC BY 4.0 | Nearest place name lookup |
| ExifTool (Phil Harvey) | GPL / Artistic | EXIF metadata extraction |
| timezonefinder | MIT | Offline timezone inference |
