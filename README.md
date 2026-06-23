# 🦅 Avian Photo Metadata Assistant

> © Aditya Rao (aditya.r.rao@gmail.com)

A macOS desktop app for bird and wildlife photographers. Select a geotagged JPEG, and the app extracts EXIF metadata, identifies the nearest place name, fetches estimated historical weather, and generates a clean description ready to paste into eBird / Macaulay Library.

---

## Features

- **EXIF extraction** — date/time, GPS coordinates, altitude (m & ft), camera, lens, exposure
- **Offline location lookup** — nearest place, region, country, distance (GeoNames ~200k places)
- **Automatic timezone inference** — IANA timezone from GPS coordinates, no internet needed
- **Historical weather** — condition, temperature (°C & °F), humidity, wind, sunrise/sunset via Open-Meteo
- **Three description templates** — default (full detail), minimal, naturalist
- **GPS privacy** — exact coordinates hidden by default; opt-in checkbox per photo
- **JIT design** — no photo files or history stored; only location/weather caches persist
- **Copy to clipboard** — one click to paste into eBird

---

## Prerequisites

```bash
# ExifTool (required)
brew install exiftool

# Python with Tk support (3.12 or 3.13 recommended)
brew install python@3.12
# If you see a _tkinter error: brew install python-tk@3.12
```

---

## Quick Start

```bash
git clone <repo-url>
cd "Avian Image Geo and Description Generator"
./run.sh
```

`run.sh` creates a `.venv/`, installs Python dependencies (`customtkinter`, `Pillow`, `timezonefinder`), and launches the app.

**First launch:** GeoNames place data (~30 MB) is downloaded and imported in the background. A progress bar appears in the left panel. This happens once only.

---

## Usage

1. Click **Choose Photo** and select a JPEG
2. EXIF metadata populates automatically
3. Location and timezone are resolved offline; weather fetches in the background
4. Confirm or change the **Local Timezone** if needed (affects weather accuracy)
5. Choose a **template** (default / minimal / naturalist)
6. Tick **Include exact GPS coords** only if appropriate (sensitive species = leave unchecked)
7. Add any **custom field notes**
8. Click **📋 Copy to Clipboard** and paste into eBird

---

## Project Structure

```
├── run.sh                              # Launcher
├── requirements.txt
├── README.md
├── avian_photo_metadata_app_design.md  # Full architecture & design doc
└── src/
    ├── main.py
    ├── models/
    │   └── photo_metadata.py
    ├── services/
    │   ├── db_service.py
    │   ├── exif_service.py
    │   ├── location_service.py
    │   ├── weather_service.py
    │   ├── template_service.py
    │   └── timezone_service.py
    └── ui/
        └── main_window.py
```

---

## Data & Privacy

- Images **never leave your Mac**
- Only lat/lon + date are sent to Open-Meteo for weather
- Cache stored at `~/Library/Application Support/AvianPhotoMetadata/avian_cache.db`
- Delete that folder at any time to wipe all cached data

---

## Attributions

| Source | License |
|---|---|
| [Open-Meteo](https://open-meteo.com) Historical Archive | CC BY 4.0 |
| [GeoNames](https://geonames.org) cities500 | CC BY 4.0 |
| [ExifTool](https://exiftool.org) — Phil Harvey | GPL / Artistic |
| [timezonefinder](https://github.com/jannikmi/timezonefinder) | MIT |
