# © Aditya Rao (aditya.r.rao@gmail.com)
"""
Avian Photo Metadata Assistant
Entry point — Milestone 2 (SQLite cache layer)
"""

import sys
import os

# Ensure the src directory is on the Python path regardless of
# where the script is invoked from.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.db_service import DatabaseService
from services.location_service import LocationService
from services.weather_service import WeatherService
from ui.main_window import MainWindow


def main():
    db = DatabaseService()
    db.init()

    location_svc = LocationService(db)
    weather_svc  = WeatherService(db)

    app = MainWindow(db=db, location_svc=location_svc, weather_svc=weather_svc)
    app.mainloop()

    db.close()


if __name__ == "__main__":
    main()
