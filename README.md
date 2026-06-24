# 🦅 Avian Photo Metadata Assistant

> © Aditya Rao (aditya.r.rao@gmail.com)

A macOS desktop app (+ CLI tool) for bird and wildlife photographers. Select a geotagged JPEG, and the app extracts EXIF metadata, identifies the nearest place name, fetches estimated historical weather, and generates a clean description ready to paste into eBird / Macaulay Library.

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
- **CLI companion** — `avianexif` terminal tool for batch processing and scripting

---

## Screenshot
<img width="1707" height="985" alt="avian-exif-ui" src="https://github.com/user-attachments/assets/06c2e921-9199-4d12-8cba-60c67b5e62f7" />


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
chmod +x run.sh bin/avianexif   # once, if needed
./run.sh
```

`run.sh` creates a `.venv/`, installs Python dependencies (`customtkinter`, `Pillow`, `timezonefinder`), installs the `avianexif` CLI on your PATH, and launches the app.

**First launch:** GeoNames place data (~30 MB) is downloaded and imported in the background. A progress bar appears in the left panel. This happens once only.

---

## GUI Usage

1. Click **Choose Photo** and select a JPEG
2. EXIF metadata populates automatically
3. Location and timezone are resolved offline; weather fetches in the background
4. Confirm or change the **Local Timezone** if needed (affects weather accuracy)
5. Choose a **template** (default / minimal / naturalist)
6. Tick **Include exact GPS coords** only if appropriate (sensitive species = leave unchecked)
7. Add any **custom field notes**
8. Click **📋 Copy to Clipboard** and paste into eBird

---

## CLI Usage (`avianexif`)

After running `./run.sh` once, the `avianexif` command is available system-wide.

```bash
# Single file
avianexif -f photo.jpg

# Glob pattern — current directory only, non-recursive
avianexif -f *.jpg

# Choose template: d=default  m=minimal  n=naturalist
avianexif -f *.jpg -t m

# Include GPS coordinates
avianexif -f '*.JPG' -t n --coords

# Custom notes appended to every photo
avianexif -f DSC001.jpg -t d -c "Seen at dawn in mixed forest"

# Redirect to file
avianexif -f *.jpg -t d > all_notes.txt

# Offline (skip weather) and copy directly to clipboard
avianexif -f *.jpg --no-weather --no-separator | pbcopy
```

### CLI flags

| Flag | Description |
|---|---|
| `-f` / `--file` | One or more files or glob patterns (current directory, non-recursive) |
| `-t d\|m\|n` | Template: default / minimal / naturalist |
| `-c TEXT` | Custom notes appended to every description |
| `--coords` | Include exact GPS coordinates (hidden by default) |
| `--no-weather` | Skip Open-Meteo — faster, fully offline |
| `--no-separator` | Suppress filename headers (useful for single-file pipe) |

Descriptions go to **stdout**; warnings go to **stderr**. Exit code 0 = success, 1 = any file failed.

---

## CLI Installation (manual / Apple Silicon fix)

`run.sh` installs the `avianexif` symlink automatically, detecting the right location:

| Mac type | Auto-install location |
|---|---|
| Apple Silicon (M1/M2/M3/M4) | `/opt/homebrew/bin` |
| Intel Mac | `/usr/local/bin` |
| Fallback (no sudo) | `~/.local/bin` |

If you need to install manually, run from the project root:

**Apple Silicon:**
```bash
sudo ln -sf "$(pwd)/bin/avianexif" /opt/homebrew/bin/avianexif
```

**Intel Mac:**
```bash
sudo mkdir -p /usr/local/bin
sudo ln -sf "$(pwd)/bin/avianexif" /usr/local/bin/avianexif
```

**No-sudo fallback (any Mac):**
```bash
mkdir -p ~/.local/bin
ln -sf "$(pwd)/bin/avianexif" ~/.local/bin/avianexif
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc
```

Verify: `avianexif --help`

---

## Project Structure

```
├── run.sh                              # Launcher + CLI installer
├── requirements.txt
├── README.md
├── avian_photo_metadata_app_design.md  # Full architecture & design doc
├── .gitignore
├── bin/
│   └── avianexif                       # Bash wrapper (symlinked to system PATH)
└── src/
    ├── main.py                         # GUI entry point
    ├── cli.py                          # CLI entry point (avianexif)
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
