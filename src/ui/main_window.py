# © Aditya Rao (aditya.r.rao@gmail.com)
"""
Main application window — Milestone 6 (MVP Polish).

Layout
------
  Header bar   (title | exiftool badge | cache badge)
  Picker bar   (Choose Photo | filename)
  ┌──────────────────────────────────────────────────────┐
  │  Preview pane (left)  │  Scrollable right panel       │
  │  thumbnail            │  📅 Date & Time               │
  │  file info            │      + timezone selector      │
  │                       │  📍 GPS Location              │
  │                       │  🗺️  Nearest Place            │
  │                       │  🌤️  Weather  [↻ Refresh]    │
  │                       │  📷 Camera & Lens             │
  │                       │  📝 Description               │
  │                       │    template dropdown          │
  │                       │    custom notes textarea      │
  │                       │    [Generate] button          │
  │                       │    editable output textarea   │
  │                       │    [Copy to Clipboard] button │
  └──────────────────────────────────────────────────────┘
  Warnings bar  |  attribution (right-aligned)
"""

import threading
import tkinter as tk
from tkinter import filedialog
from pathlib import Path
from typing import Optional

import customtkinter as ctk
from PIL import Image

from services.exif_service import extract_exif, exiftool_version
from services.db_service import DatabaseService
from services.location_service import LocationService
from services.weather_service import WeatherService
from services.template_service import generate as generate_description
from services.timezone_service import best_timezone, COMMON_TIMEZONES
from models.photo_metadata import PhotoMetadata

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

_COLOR_LABEL   = "#888888"
_COLOR_WARN    = "#FFA040"
_COLOR_OK      = "#4CAF82"
_COLOR_MISSING = "#555555"

_PREVIEW_SIZE  = 300   # px, square cap for thumbnail
_COPY_RESET_MS = 2500  # ms before "Copied!" label resets


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(ctk.CTk):

    def __init__(
        self,
        db: Optional[DatabaseService] = None,
        location_svc: Optional[LocationService] = None,
        weather_svc:  Optional[WeatherService]  = None,
    ):
        super().__init__()

        self.title("Avian Photo Metadata Assistant")
        self.geometry("1050x860")
        self.minsize(900, 680)

        self._db = db
        self._location_svc = location_svc
        self._weather_svc  = weather_svc
        self._current_metadata: Optional[PhotoMetadata] = None
        self._current_location: Optional[dict] = None
        self._current_weather:  Optional[dict] = None
        self._current_timezone: Optional[str]  = None   # M6: IANA timezone
        self._ctk_image = None

        self._build_ui()
        self._check_exiftool_on_start()
        self._update_cache_badge()
        self._check_places_on_start()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self._build_header()
        self._build_picker()
        self._build_content()
        self._build_warnings()

    def _build_header(self):
        frame = ctk.CTkFrame(self, height=56, corner_radius=0, fg_color="#1A1A2E")
        frame.grid(row=0, column=0, sticky="ew")
        frame.grid_propagate(False)

        ctk.CTkLabel(
            frame,
            text="🦅   Avian Photo Metadata Assistant",
            font=ctk.CTkFont(family="SF Pro Display", size=20, weight="bold"),
            text_color="#E0E0E0",
        ).pack(side="left", padx=20, pady=14)

        self._cache_badge = ctk.CTkLabel(
            frame, text="", font=ctk.CTkFont(size=11), text_color=_COLOR_OK,
        )
        self._cache_badge.pack(side="right", padx=8)

        self._exiftool_badge = ctk.CTkLabel(
            frame, text="", font=ctk.CTkFont(size=11), text_color=_COLOR_WARN,
        )
        self._exiftool_badge.pack(side="right", padx=8)

    def _build_picker(self):
        frame = ctk.CTkFrame(self, height=52, corner_radius=0, fg_color="#141428")
        frame.grid(row=1, column=0, sticky="ew")
        frame.grid_propagate(False)

        ctk.CTkButton(
            frame, text="  Choose Photo", width=140, height=34,
            font=ctk.CTkFont(size=13), command=self._choose_photo,
        ).pack(side="left", padx=12, pady=9)

        self._file_label = ctk.CTkLabel(
            frame, text="No photo selected", text_color=_COLOR_LABEL,
            font=ctk.CTkFont(size=12), anchor="w",
        )
        self._file_label.pack(side="left", padx=4, fill="x", expand=True)

    def _build_content(self):
        outer = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        outer.grid(row=2, column=0, sticky="nsew", padx=10, pady=10)
        outer.grid_rowconfigure(0, weight=1)
        outer.grid_columnconfigure(1, weight=1)

        # -- Left: photo preview --
        preview_frame = ctk.CTkFrame(outer, width=_PREVIEW_SIZE + 20, corner_radius=10)
        preview_frame.grid(row=0, column=0, sticky="ns", padx=(0, 8))
        preview_frame.grid_propagate(False)

        self._preview_label = ctk.CTkLabel(
            preview_frame, text="No photo\nselected",
            text_color=_COLOR_LABEL, font=ctk.CTkFont(size=13),
            width=_PREVIEW_SIZE, height=_PREVIEW_SIZE,
        )
        self._preview_label.pack(padx=10, pady=10)

        self._file_info = ctk.CTkLabel(
            preview_frame, text="", text_color=_COLOR_LABEL,
            font=ctk.CTkFont(size=10), wraplength=_PREVIEW_SIZE, justify="center",
        )
        self._file_info.pack(padx=10, pady=(0, 6))

        # GeoNames setup progress (shown on first run only)
        self._setup_label = ctk.CTkLabel(
            preview_frame, text="", text_color=_COLOR_WARN,
            font=ctk.CTkFont(size=10), wraplength=_PREVIEW_SIZE, justify="center",
        )
        self._setup_label.pack(padx=10)

        self._setup_bar = ctk.CTkProgressBar(preview_frame, width=_PREVIEW_SIZE)
        self._setup_bar.set(0)
        # hidden until needed

        # -- Right: scrollable panel --
        right = ctk.CTkScrollableFrame(outer, corner_radius=10, label_text="")
        right.grid(row=0, column=1, sticky="nsew")

        self._val = {}

        # Date & Time section — custom (has timezone selector)
        self._build_datetime_section(right)

        self._build_section(right, "📍   GPS Location", [
            ("Coordinates", "coords"),
            ("Altitude",    "gps_altitude_m"),
        ])

        self._build_section(right, "🗺️   Nearest Place", [
            ("Place",       "loc_place"),
            ("Region",      "loc_region"),
            ("Country",     "loc_country"),
            ("Distance",    "loc_distance"),
            ("Source",      "loc_source"),
        ])

        # Weather section — custom (has Refresh button)
        self._build_weather_section(right)

        self._build_section(right, "📷   Camera & Lens", [
            ("Camera",       "camera"),
            ("Lens",         "lens_model"),
            ("Focal Length", "focal_length"),
            ("Exposure",     "exposure"),
            ("ISO",          "iso"),
        ])

        self._build_description_section(right)

    # ------------------------------------------------------------------
    # Specialised section builders
    # ------------------------------------------------------------------

    def _build_datetime_section(self, parent):
        """Date & Time section with timezone selector row."""
        section = ctk.CTkFrame(parent, corner_radius=8)
        section.pack(fill="x", pady=(0, 10), padx=2)

        ctk.CTkLabel(
            section, text="📅   Date & Time",
            font=ctk.CTkFont(size=13, weight="bold"), anchor="w",
        ).pack(fill="x", padx=14, pady=(10, 6))

        ctk.CTkFrame(section, height=1, fg_color="#333355").pack(fill="x", padx=14)

        for label_text, attr_key in [
            ("Date / Time",     "date_time_original"),
            ("Timezone Offset", "offset_time_original"),
            ("GPS DateTime",    "gps_date_time"),
        ]:
            row = ctk.CTkFrame(section, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=4)

            ctk.CTkLabel(
                row, text=label_text + ":", width=140, anchor="w",
                text_color=_COLOR_LABEL, font=ctk.CTkFont(size=12),
            ).pack(side="left")

            val = ctk.CTkLabel(
                row, text="—", anchor="w",
                font=ctk.CTkFont(size=12), text_color=_COLOR_MISSING, wraplength=430,
            )
            val.pack(side="left", fill="x", expand=True)
            self._val[attr_key] = val

        # --- Timezone selector row ---
        tz_row = ctk.CTkFrame(section, fg_color="transparent")
        tz_row.pack(fill="x", padx=14, pady=4)

        ctk.CTkLabel(
            tz_row, text="Local Timezone:", width=140, anchor="w",
            text_color=_COLOR_LABEL, font=ctk.CTkFont(size=12),
        ).pack(side="left")

        self._tz_var = ctk.StringVar(value="UTC")
        self._tz_combo = ctk.CTkComboBox(
            tz_row,
            values=COMMON_TIMEZONES,
            variable=self._tz_var,
            width=220,
            font=ctk.CTkFont(size=12),
            command=self._on_timezone_change,
            state="disabled",
        )
        self._tz_combo.pack(side="left")

        self._tz_source_label = ctk.CTkLabel(
            tz_row, text="(load a photo)", text_color=_COLOR_LABEL,
            font=ctk.CTkFont(size=11),
        )
        self._tz_source_label.pack(side="left", padx=10)

        ctk.CTkFrame(section, height=1, fg_color="#222244").pack(fill="x", padx=14, pady=(6, 10))

    def _build_weather_section(self, parent):
        """Weather section with Refresh button in header."""
        section = ctk.CTkFrame(parent, corner_radius=8)
        section.pack(fill="x", pady=(0, 10), padx=2)

        # Header row: title + Refresh button
        header_row = ctk.CTkFrame(section, fg_color="transparent")
        header_row.pack(fill="x", padx=14, pady=(10, 6))

        ctk.CTkLabel(
            header_row, text="🌤️   Weather (estimated historical)",
            font=ctk.CTkFont(size=13, weight="bold"), anchor="w",
        ).pack(side="left")

        self._refresh_weather_btn = ctk.CTkButton(
            header_row, text="↻  Refresh", width=90, height=26,
            font=ctk.CTkFont(size=11), command=self._refresh_weather,
            state="disabled",
        )
        self._refresh_weather_btn.pack(side="right")

        ctk.CTkFrame(section, height=1, fg_color="#333355").pack(fill="x", padx=14)

        for label_text, attr_key in [
            ("Condition",      "wx_condition"),
            ("Temperature",    "wx_temp"),
            ("Wind",           "wx_wind"),
            ("Wind Direction", "wx_wind_dir"),
            ("Cloud Cover",    "wx_cloud"),
            ("Humidity",       "wx_humidity"),
            ("Sunrise",        "wx_sunrise"),
            ("Sunset",         "wx_sunset"),
            ("Matched time",   "wx_matched"),
        ]:
            row = ctk.CTkFrame(section, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=4)

            ctk.CTkLabel(
                row, text=label_text + ":", width=140, anchor="w",
                text_color=_COLOR_LABEL, font=ctk.CTkFont(size=12),
            ).pack(side="left")

            val = ctk.CTkLabel(
                row, text="—", anchor="w",
                font=ctk.CTkFont(size=12), text_color=_COLOR_MISSING, wraplength=430,
            )
            val.pack(side="left", fill="x", expand=True)
            self._val[attr_key] = val

        ctk.CTkFrame(section, height=1, fg_color="#222244").pack(fill="x", padx=14, pady=(6, 10))

    def _build_section(self, parent, title: str, fields: list):
        section = ctk.CTkFrame(parent, corner_radius=8)
        section.pack(fill="x", pady=(0, 10), padx=2)

        ctk.CTkLabel(
            section, text=title,
            font=ctk.CTkFont(size=13, weight="bold"), anchor="w",
        ).pack(fill="x", padx=14, pady=(10, 6))

        ctk.CTkFrame(section, height=1, fg_color="#333355").pack(fill="x", padx=14)

        for label_text, attr_key in fields:
            row = ctk.CTkFrame(section, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=4)

            ctk.CTkLabel(
                row, text=label_text + ":", width=140, anchor="w",
                text_color=_COLOR_LABEL, font=ctk.CTkFont(size=12),
            ).pack(side="left")

            val = ctk.CTkLabel(
                row, text="—", anchor="w",
                font=ctk.CTkFont(size=12), text_color=_COLOR_MISSING, wraplength=430,
            )
            val.pack(side="left", fill="x", expand=True)
            self._val[attr_key] = val

        ctk.CTkFrame(section, height=1, fg_color="#222244").pack(fill="x", padx=14, pady=(6, 10))

    def _build_description_section(self, parent):
        section = ctk.CTkFrame(parent, corner_radius=8)
        section.pack(fill="x", pady=(0, 10), padx=2)

        # Section header
        ctk.CTkLabel(
            section, text="📝   Description",
            font=ctk.CTkFont(size=13, weight="bold"), anchor="w",
        ).pack(fill="x", padx=14, pady=(10, 6))

        ctk.CTkFrame(section, height=1, fg_color="#333355").pack(fill="x", padx=14)

        # Template selector row
        tmpl_row = ctk.CTkFrame(section, fg_color="transparent")
        tmpl_row.pack(fill="x", padx=14, pady=(10, 4))

        ctk.CTkLabel(
            tmpl_row, text="Template:", width=100, anchor="w",
            text_color=_COLOR_LABEL, font=ctk.CTkFont(size=12),
        ).pack(side="left")

        template_names = ["default", "minimal", "naturalist"]
        if self._db:
            try:
                template_names = [t["name"] for t in self._db.get_all_templates()]
            except Exception:
                pass

        self._template_var = ctk.StringVar(value=template_names[0])
        ctk.CTkOptionMenu(
            tmpl_row, values=template_names, variable=self._template_var,
            width=160, font=ctk.CTkFont(size=12),
        ).pack(side="left")

        # Auto-regenerate when template changes
        self._template_var.trace_add("write", lambda *_: self._generate())

        # GPS coordinates checkbox — right side of template row
        self._show_coords_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            tmpl_row,
            text="Include exact GPS coords",
            variable=self._show_coords_var,
            font=ctk.CTkFont(size=12),
            checkbox_width=18, checkbox_height=18,
            command=self._generate,   # regenerate on toggle
        ).pack(side="right")

        # Custom notes label + text box
        ctk.CTkLabel(
            section, text="Custom field notes:",
            text_color=_COLOR_LABEL, font=ctk.CTkFont(size=12), anchor="w",
        ).pack(fill="x", padx=14, pady=(10, 4))

        self._custom_text = ctk.CTkTextbox(
            section, height=80, font=ctk.CTkFont(size=12),
            wrap="word", border_width=1, border_color="#333355",
        )
        self._custom_text.pack(fill="x", padx=14, pady=(0, 10))
        self._custom_text.insert("0.0",
            "e.g. Seen foraging quietly in the canopy. Active calling at dawn.")

        # Generate button
        ctk.CTkButton(
            section, text="⚡  Generate Description", height=36,
            font=ctk.CTkFont(size=13), command=self._generate,
        ).pack(fill="x", padx=14, pady=(0, 10))

        ctk.CTkFrame(section, height=1, fg_color="#333355").pack(fill="x", padx=14)

        # Generated output (editable so user can tweak before copying)
        ctk.CTkLabel(
            section, text="Generated description (editable):",
            text_color=_COLOR_LABEL, font=ctk.CTkFont(size=12), anchor="w",
        ).pack(fill="x", padx=14, pady=(10, 4))

        self._output_text = ctk.CTkTextbox(
            section, height=160, font=ctk.CTkFont(size=12),
            wrap="word", border_width=1, border_color="#333355",
        )
        self._output_text.pack(fill="x", padx=14, pady=(0, 10))
        self._output_text.configure(state="disabled")

        # Copy row: button + feedback label
        copy_row = ctk.CTkFrame(section, fg_color="transparent")
        copy_row.pack(fill="x", padx=14, pady=(0, 14))

        self._copy_btn = ctk.CTkButton(
            copy_row, text="📋  Copy to Clipboard", width=180, height=34,
            font=ctk.CTkFont(size=13), command=self._copy_to_clipboard,
        )
        self._copy_btn.pack(side="left")

        self._copy_feedback = ctk.CTkLabel(
            copy_row, text="", text_color=_COLOR_OK,
            font=ctk.CTkFont(size=12),
        )
        self._copy_feedback.pack(side="left", padx=12)

    def _build_warnings(self):
        frame = ctk.CTkFrame(self, height=32, corner_radius=0, fg_color="#0F0F1E")
        frame.grid(row=3, column=0, sticky="ew")
        frame.grid_propagate(False)

        # Attribution — right-aligned, always visible
        ctk.CTkLabel(
            frame,
            text="Weather: Open-Meteo CC BY 4.0  ·  Places: GeoNames CC BY 4.0",
            text_color="#3A3A5C", font=ctk.CTkFont(size=10),
        ).pack(side="right", padx=14)

        self._warn_label = ctk.CTkLabel(
            frame, text="", text_color=_COLOR_WARN,
            font=ctk.CTkFont(size=11), anchor="w",
        )
        self._warn_label.pack(side="left", padx=14, pady=6)

    # ------------------------------------------------------------------
    # Photo loading
    # ------------------------------------------------------------------

    def _choose_photo(self):
        path = filedialog.askopenfilename(
            title="Select a bird photo",
            filetypes=[
                ("JPEG files", "*.jpg *.jpeg *.JPG *.JPEG"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self._load_photo(path)

    def _load_photo(self, path: str):
        filename = Path(path).name
        self.title(f"Avian — {filename}")          # M6: window title shows filename
        self._file_label.configure(text=str(Path(path)), text_color="#CCCCCC")
        self._load_thumbnail(path)

        # Reset state from any previous photo
        self._current_location = None
        self._current_weather  = None
        self._current_timezone = None

        # Reset timezone combo to pending state
        self._tz_var.set("UTC")
        self._tz_source_label.configure(text="(inferring…)")
        self._tz_combo.configure(state="disabled")
        self._refresh_weather_btn.configure(state="disabled")

        meta = extract_exif(path)
        self._current_metadata = meta
        self._populate_metadata(meta)
        self._populate_location(None)
        self._populate_weather(None)
        self._show_warnings(meta.warnings)

        # Initial description without location (updates again after lookup)
        self._generate()

        # Kick off location lookup if GPS available
        if meta.has_gps and self._location_svc:
            if self._location_svc.places_loaded():
                self._run_location_lookup(meta.latitude, meta.longitude)
            else:
                self._show_warnings(
                    meta.warnings + ["Place data not yet downloaded — location lookup skipped."]
                )
                # Still set timezone from EXIF offset if GPS is available
                self._resolve_timezone_from_exif(meta)

    def _load_thumbnail(self, path: str):
        try:
            img = Image.open(path)
            size_kb = Path(path).stat().st_size / 1024
            size_str = f"{size_kb/1024:.1f} MB" if size_kb > 1024 else f"{size_kb:.0f} KB"
            w_orig, h_orig = img.size
            img.thumbnail((_PREVIEW_SIZE, _PREVIEW_SIZE), Image.LANCZOS)
            w_t, h_t = img.size
            self._ctk_image = ctk.CTkImage(light_image=img, dark_image=img, size=(w_t, h_t))
            self._preview_label.configure(image=self._ctk_image, text="")
            self._file_info.configure(text=f"{w_orig} × {h_orig} px  •  {size_str}")
        except Exception as e:
            self._preview_label.configure(text=f"Preview unavailable\n{e}", image=None)
            self._file_info.configure(text="")

    # ------------------------------------------------------------------
    # Timezone
    # ------------------------------------------------------------------

    def _resolve_timezone_from_exif(self, meta: PhotoMetadata):
        """Set timezone from EXIF offset (no GPS). Shows a note to confirm."""
        if meta.offset_time_original:
            # Can't infer IANA from offset alone — show UTC with prompt
            self._tz_var.set("UTC")
            self._tz_source_label.configure(
                text=f"EXIF offset {meta.offset_time_original} — please select from list",
                text_color=_COLOR_WARN,
            )
        else:
            self._tz_var.set("UTC")
            self._tz_source_label.configure(
                text="(no GPS — please confirm timezone)", text_color=_COLOR_WARN,
            )
        self._tz_combo.configure(state="normal")
        self._current_timezone = "UTC"

    def _on_timezone_change(self, tz: str):
        """Called when user selects or types a timezone in the ComboBox."""
        tz = tz.strip()
        if not tz:
            return
        self._current_timezone = tz
        self._tz_source_label.configure(text="(user selected)", text_color=_COLOR_OK)
        self._generate()

        # Re-trigger weather with confirmed timezone
        meta = self._current_metadata
        if meta and meta.has_gps and meta.date_time_original and self._weather_svc:
            self._run_weather_lookup(meta.latitude, meta.longitude,
                                      meta.date_time_original, tz)

    def _refresh_weather(self):
        """Refresh weather with current confirmed timezone."""
        meta = self._current_metadata
        if not meta or not meta.has_gps or not meta.date_time_original:
            return
        tz = self._current_timezone or "auto"
        self._refresh_weather_btn.configure(state="disabled")
        self._populate_weather(None)
        self._run_weather_lookup(meta.latitude, meta.longitude,
                                  meta.date_time_original, tz)

    # ------------------------------------------------------------------
    # Metadata display
    # ------------------------------------------------------------------

    def _populate_metadata(self, m: PhotoMetadata):
        def sv(key, text, ok=True):
            color = "#E0E0E0" if (ok and text != "—") else _COLOR_MISSING
            if key in self._val:
                self._val[key].configure(text=text, text_color=color)

        sv("date_time_original",  m.date_time_original or "—",  ok=bool(m.date_time_original))
        sv("offset_time_original", m.offset_time_original or "—", ok=bool(m.offset_time_original))
        sv("gps_date_time",       m.gps_date_time or "—",        ok=bool(m.gps_date_time))
        sv("coords",              m.coords_display,               ok=m.has_gps)
        sv("gps_altitude_m",      m.altitude_display,             ok=m.gps_altitude_m is not None)
        sv("camera",              m.camera_display,               ok=bool(m.camera_make or m.camera_model))
        sv("lens_model",          m.lens_model or "—",            ok=bool(m.lens_model))
        sv("focal_length",        m.focal_length or "—",          ok=bool(m.focal_length))
        exp_parts = [p for p in [
            m.exposure_time,
            f"f/{m.f_number}" if m.f_number else None,
        ] if p]
        sv("exposure", "   ".join(exp_parts) or "—", ok=bool(exp_parts))
        sv("iso", str(m.iso) if m.iso else "—", ok=bool(m.iso))

    # ------------------------------------------------------------------
    # Description generation + clipboard
    # ------------------------------------------------------------------

    def _generate(self):
        if self._current_metadata is None:
            self._set_output("Load a photo first to generate a description.")
            return

        custom = self._custom_text.get("0.0", "end").strip()
        # Clear the placeholder hint if still present
        if custom.startswith("e.g."):
            custom = ""

        template_name = self._template_var.get()

        text, warnings = generate_description(
            metadata=self._current_metadata,
            template_name=template_name,
            db=self._db,
            location=self._current_location,
            weather=self._current_weather,
            custom_text=custom,
            timezone_str=self._current_timezone,   # M6: confirmed IANA timezone
            show_coords=self._show_coords_var.get(),
        )

        self._set_output(text)

        # Merge generation warnings with EXIF warnings
        all_warnings = (self._current_metadata.warnings or []) + warnings
        self._show_warnings(all_warnings)

    def _set_output(self, text: str):
        self._output_text.configure(state="normal")
        self._output_text.delete("0.0", "end")
        self._output_text.insert("0.0", text)
        self._output_text.configure(state="disabled")

    def _copy_to_clipboard(self):
        text = self._output_text.get("0.0", "end").strip()
        if not text or text == "Load a photo first to generate a description.":
            self._copy_feedback.configure(text="Nothing to copy yet.", text_color=_COLOR_WARN)
            self.after(_COPY_RESET_MS, lambda: self._copy_feedback.configure(text=""))
            return

        self.clipboard_clear()
        self.clipboard_append(text)
        self.update()   # flush clipboard to OS

        # M6: brief disable after copy
        self._copy_btn.configure(state="disabled", text="✅  Copied!")
        self._copy_feedback.configure(text="", text_color=_COLOR_OK)
        self.after(_COPY_RESET_MS, self._reset_copy_btn)

    def _reset_copy_btn(self):
        self._copy_btn.configure(state="normal", text="📋  Copy to Clipboard")

    # ------------------------------------------------------------------
    # Warnings bar
    # ------------------------------------------------------------------

    def _show_warnings(self, warnings: list):
        if not warnings:
            self._warn_label.configure(
                text="✅  EXIF extracted successfully", text_color=_COLOR_OK,
            )
        else:
            joined = "   ·   ".join(warnings)
            self._warn_label.configure(text=f"⚠️  {joined}", text_color=_COLOR_WARN)

    # ------------------------------------------------------------------
    # Location panel helpers
    # ------------------------------------------------------------------

    def _populate_location(self, loc: Optional[dict]):
        def sv(key, text, ok=True):
            color = "#E0E0E0" if (ok and text != "—") else _COLOR_MISSING
            if key in self._val:
                self._val[key].configure(text=text, text_color=color)

        if loc:
            sv("loc_place",    loc.get("nearest_place") or "—", ok=True)
            sv("loc_region",   loc.get("admin_region")  or "—", ok=bool(loc.get("admin_region")))
            sv("loc_country",  loc.get("country")       or "—", ok=bool(loc.get("country")))
            dist = loc.get("distance_km")
            sv("loc_distance", f"{dist:.1f} km" if dist is not None else "—", ok=dist is not None)
            src = loc.get("source", "")
            conf = loc.get("confidence", "")
            sv("loc_source",   f"{src}  ({conf})" if conf else src, ok=True)
        else:
            for k in ("loc_place", "loc_region", "loc_country", "loc_distance", "loc_source"):
                sv(k, "—", ok=False)

    def _run_location_lookup(self, lat: float, lon: float):
        """Run lookup in background thread; update UI when done."""
        def _worker():
            try:
                result = self._location_svc.lookup(lat, lon)
            except Exception:
                result = None
            self.after(0, lambda: self._on_location_result(result))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_location_result(self, result: Optional[dict]):
        self._current_location = result
        self._populate_location(result)
        self._update_cache_badge()

        # M6: infer IANA timezone from GPS now that we've confirmed coordinates
        meta = self._current_metadata
        if meta and meta.has_gps:
            tz, source = best_timezone(
                meta.latitude, meta.longitude, meta.offset_time_original
            )
            self._current_timezone = tz
            self._tz_var.set(tz)
            self._tz_source_label.configure(
                text=f"({source})", text_color=_COLOR_OK,
            )
            self._tz_combo.configure(state="normal")

        self._generate()

        # Kick off weather lookup with confirmed timezone
        if meta and meta.has_gps and meta.date_time_original:
            tz_for_weather = self._current_timezone or "auto"
            self._run_weather_lookup(meta.latitude, meta.longitude,
                                      meta.date_time_original, tz_for_weather)

    # ------------------------------------------------------------------
    # Weather panel + lookup
    # ------------------------------------------------------------------

    def _populate_weather(self, wx: Optional[dict]):
        def sv(key, text, ok=True):
            color = "#E0E0E0" if (ok and text not in ("—", "")) else _COLOR_MISSING
            if key in self._val:
                self._val[key].configure(text=text, text_color=color)

        if wx:
            temp  = wx.get("temperature_c")
            hum   = wx.get("relative_humidity")
            cloud = wx.get("cloud_cover_pct")
            wspd  = wx.get("wind_speed_kmh")

            sv("wx_condition", wx.get("condition") or "—")
            sv("wx_temp",
               f"{temp:.0f}°C  ({temp * 9/5 + 32:.0f}°F)" if temp is not None else "—",
               ok=temp is not None)
            sv("wx_wind",
               f"{wx.get('wind_label', '—')}  ({wspd:.0f} km/h)" if wspd is not None else "—",
               ok=wspd is not None)
            sv("wx_wind_dir",  wx.get("wind_dir")  or "—")
            sv("wx_cloud",
               f"{cloud:.0f}%" if cloud is not None else "—",
               ok=cloud is not None)
            sv("wx_humidity",
               f"{hum:.0f}%"   if hum   is not None else "—",
               ok=hum is not None)
            sv("wx_sunrise",   wx.get("sunrise") or "—")
            sv("wx_sunset",    wx.get("sunset")  or "—")
            matched = wx.get("matched_time") or ""
            cached  = "  (cached)" if wx.get("from_cache") else ""
            sv("wx_matched",   f"{matched}{cached}" if matched else "—")
        else:
            for k in ("wx_condition","wx_temp","wx_wind","wx_wind_dir",
                      "wx_cloud","wx_humidity","wx_sunrise","wx_sunset","wx_matched"):
                sv(k, "—", ok=False)

    def _run_weather_lookup(
        self, lat: float, lon: float, dt_str: str, tz: str
    ):
        def _worker():
            try:
                result, err = self._weather_svc.lookup(lat, lon, dt_str, tz)
            except Exception as e:
                result, err = None, str(e)
            self.after(0, lambda: self._on_weather_result(result, err))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_weather_result(self, result: Optional[dict], error: Optional[str]):
        self._current_weather = result
        self._populate_weather(result)
        self._update_cache_badge()
        self._generate()

        # M6: re-enable Refresh button after lookup completes
        meta = self._current_metadata
        if meta and meta.has_gps and meta.date_time_original:
            self._refresh_weather_btn.configure(state="normal")

        if result is None:
            msg = f"Weather unavailable — {error}" if error else "Weather unavailable."
            base = meta.warnings if meta else []
            self._show_warnings(base + [msg])

    # ------------------------------------------------------------------
    # GeoNames first-run setup
    # ------------------------------------------------------------------

    def _check_places_on_start(self):
        if self._location_svc is None:
            return
        if self._location_svc.places_loaded():
            return
        # Kick off download in background
        self._setup_label.configure(text="Downloading place data (first run)…")
        self._setup_bar.pack(padx=10, pady=(2, 10))
        self._setup_bar.set(0)

        def _worker():
            self._location_svc.download_and_import(
                progress_cb=self._on_setup_progress
            )

        threading.Thread(target=_worker, daemon=True).start()

    def _on_setup_progress(self, message: str, pct: float):
        def _update():
            if pct < 0:   # error
                self._setup_label.configure(text=f"⚠️ {message}", text_color=_COLOR_WARN)
                self._setup_bar.pack_forget()
            elif pct >= 1.0:
                self._setup_label.configure(text="✅ Place data ready", text_color=_COLOR_OK)
                self._setup_bar.pack_forget()
                self._update_cache_badge()
            else:
                self._setup_label.configure(text=message, text_color=_COLOR_WARN)
                self._setup_bar.set(pct)
        self.after(0, _update)

    # ------------------------------------------------------------------
    # Header badges
    # ------------------------------------------------------------------

    def _check_exiftool_on_start(self):
        ver = exiftool_version()
        if ver:
            self._exiftool_badge.configure(
                text=f"ExifTool {ver}  ✓", text_color=_COLOR_OK,
            )
        else:
            self._exiftool_badge.configure(
                text="ExifTool not found — brew install exiftool",
                text_color=_COLOR_WARN,
            )

    def _update_cache_badge(self):
        if self._db is None:
            self._cache_badge.configure(text="")
            return
        try:
            stats = self._db.cache_stats()
            loc, wx = stats["location_cache"], stats["weather_cache"]
            self._cache_badge.configure(
                text=f"Cache: {loc} loc  {wx} wx",
                text_color=_COLOR_OK if (loc + wx) > 0 else _COLOR_LABEL,
            )
        except Exception:
            self._cache_badge.configure(text="cache error", text_color=_COLOR_WARN)
