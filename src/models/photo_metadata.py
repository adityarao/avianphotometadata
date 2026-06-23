# © Aditya Rao (aditya.r.rao@gmail.com)
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PhotoMetadata:
    """All EXIF-derived metadata for a single photo."""

    file_path: str
    file_name: str

    # --- Timestamps ---
    date_time_original: Optional[str] = None   # e.g. "2026:06:18 07:42:00"
    offset_time_original: Optional[str] = None  # e.g. "+05:30"
    gps_date_time: Optional[str] = None         # UTC GPS timestamp if present

    # --- GPS ---
    latitude: Optional[float] = None            # decimal degrees
    longitude: Optional[float] = None           # decimal degrees
    gps_altitude_m: Optional[float] = None      # metres above sea level

    # --- Camera body ---
    camera_make: Optional[str] = None
    camera_model: Optional[str] = None

    # --- Lens & exposure ---
    lens_model: Optional[str] = None
    focal_length: Optional[str] = None          # e.g. "400mm"
    exposure_time: Optional[str] = None         # e.g. "1/2500s"
    f_number: Optional[float] = None            # e.g. 2.8
    iso: Optional[int] = None

    # --- Raw EXIF blob (for debugging / future fields) ---
    raw_exif: dict = field(default_factory=dict)

    # --- Processing warnings shown to user ---
    warnings: list = field(default_factory=list)

    # --- Convenience properties ---

    @property
    def has_gps(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    @property
    def camera_display(self) -> str:
        parts = [p for p in [self.camera_make, self.camera_model] if p]
        return " ".join(parts) if parts else "Unknown"

    @property
    def coords_display(self) -> str:
        if not self.has_gps:
            return "—"
        lat_hem = "N" if self.latitude >= 0 else "S"
        lon_hem = "E" if self.longitude >= 0 else "W"
        return f"{abs(self.latitude):.6f}°{lat_hem},  {abs(self.longitude):.6f}°{lon_hem}"

    @property
    def altitude_display(self) -> str:
        if self.gps_altitude_m is None:
            return "—"
        ft = self.gps_altitude_m * 3.28084
        return f"{self.gps_altitude_m:,.0f} m  ({ft:,.0f} ft)"
