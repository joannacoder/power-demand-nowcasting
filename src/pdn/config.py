"""Project paths and the balancing-authority universe."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
FIGURES = ROOT / "reports" / "figures"

FIRST_YEAR = 2019

# Balancing authorities in scope, with weather points used for a simple
# population-weighted temperature. Weights are rough metro-population shares
# and are a documented modelling assumption, not ground truth.
# Each entry: BA code -> list of (city, lat, lon, weight)
BA_WEATHER = {
    # ISOs / RTOs
    "ERCO": [("Houston", 29.76, -95.37, 0.35), ("Dallas", 32.78, -96.80, 0.40),
             ("San Antonio", 29.42, -98.49, 0.15), ("Austin", 30.27, -97.74, 0.10)],
    "PJM":  [("Philadelphia", 39.95, -75.17, 0.25), ("Washington", 38.91, -77.04, 0.25),
             ("Chicago", 41.88, -87.63, 0.25), ("Columbus", 39.96, -83.00, 0.15),
             ("Newark", 40.74, -74.17, 0.10)],
    "MISO": [("Minneapolis", 44.98, -93.27, 0.25), ("Detroit", 42.33, -83.05, 0.25),
             ("St. Louis", 38.63, -90.20, 0.20), ("Indianapolis", 39.77, -86.16, 0.15),
             ("New Orleans", 29.95, -90.07, 0.15)],
    "CISO": [("Los Angeles", 34.05, -118.24, 0.50), ("San Francisco", 37.77, -122.42, 0.30),
             ("Sacramento", 38.58, -121.49, 0.10), ("Fresno", 36.74, -119.79, 0.10)],
    "NYIS": [("New York", 40.71, -74.01, 0.75), ("Buffalo", 42.89, -78.88, 0.10),
             ("Albany", 42.65, -73.76, 0.15)],
    "ISNE": [("Boston", 42.36, -71.06, 0.60), ("Hartford", 41.76, -72.68, 0.25),
             ("Providence", 41.82, -71.41, 0.15)],
    "SWPP": [("Oklahoma City", 35.47, -97.52, 0.35), ("Kansas City", 39.10, -94.58, 0.35),
             ("Omaha", 41.26, -95.93, 0.30)],
    # Vertically integrated utility BAs (map to listed equities)
    "DUK":  [("Charlotte", 35.23, -80.84, 0.6), ("Greensboro", 36.07, -79.79, 0.4)],
    "CPLE": [("Raleigh", 35.78, -78.64, 1.0)],
    "FPC":  [("Orlando", 28.54, -81.38, 0.5), ("St. Petersburg", 27.77, -82.64, 0.5)],
    "FPL":  [("Miami", 25.76, -80.19, 0.6), ("West Palm Beach", 26.72, -80.05, 0.4)],
    "SOCO": [("Atlanta", 33.75, -84.39, 0.7), ("Birmingham", 33.52, -86.80, 0.3)],
    "TEC":  [("Tampa", 27.95, -82.46, 1.0)],
    "AZPS": [("Phoenix", 33.45, -112.07, 1.0)],
    "PSCO": [("Denver", 39.74, -104.99, 1.0)],
    "NEVP": [("Las Vegas", 36.17, -115.14, 1.0)],
    "PNM":  [("Albuquerque", 35.08, -106.65, 1.0)],
    "IPCO": [("Boise", 43.62, -116.20, 1.0)],
    "PGE":  [("Portland", 45.52, -122.68, 1.0)],
    "LGEE": [("Louisville", 38.25, -85.76, 0.6), ("Lexington", 38.04, -84.50, 0.4)],
    "SCEG": [("Columbia SC", 34.00, -81.03, 1.0)],
    "TVA":  [("Nashville", 36.16, -86.78, 0.5), ("Memphis", 35.15, -90.05, 0.3),
             ("Knoxville", 35.96, -83.92, 0.2)],
}

# PJM transmission zones published in the EIA-930 SUBREGION files.
# Dominion (DOM) covers Northern Virginia, the largest US data-center market.
# Weights are rough load shares (a documented assumption).
ZONE_WEATHER = {
    "DOM": [("Dulles/Ashburn", 38.95, -77.45, 0.45), ("Richmond", 37.54, -77.44, 0.30),
            ("Norfolk", 36.85, -76.29, 0.25)],
}
ZONE_PARENT = {"DOM": "PJM"}

BAS = list(BA_WEATHER)          # balancing authorities (EIA-930 BALANCE files)
ZONES = list(ZONE_WEATHER)      # subregions (EIA-930 SUBREGION files)
ALL_WEATHER = {**BA_WEATHER, **ZONE_WEATHER}

# Local time zone per BA, used to build local calendar days.
BA_TZ = {
    "ERCO": "America/Chicago", "PJM": "America/New_York", "MISO": "America/Chicago",
    "CISO": "America/Los_Angeles", "NYIS": "America/New_York", "ISNE": "America/New_York",
    "SWPP": "America/Chicago", "DUK": "America/New_York", "CPLE": "America/New_York",
    "FPC": "America/New_York", "FPL": "America/New_York", "SOCO": "America/New_York",
    "TEC": "America/New_York", "AZPS": "America/Phoenix", "PSCO": "America/Denver",
    "NEVP": "America/Los_Angeles", "PNM": "America/Denver", "IPCO": "America/Boise",
    "PGE": "America/Los_Angeles", "LGEE": "America/New_York", "SCEG": "America/New_York",
    "TVA": "America/Chicago",
    "DOM": "America/New_York",
}

BA_NAME = {
    "ERCO": "ERCOT (Texas)", "PJM": "PJM (Mid-Atlantic/Midwest)", "MISO": "MISO (Midwest)",
    "CISO": "CAISO (California)", "NYIS": "NYISO (New York)", "ISNE": "ISO-NE (New England)",
    "SWPP": "SPP (Plains)", "DUK": "Duke Energy Carolinas", "CPLE": "Duke Energy Progress East",
    "FPC": "Duke Energy Florida", "FPL": "Florida Power & Light", "SOCO": "Southern Company",
    "TEC": "Tampa Electric", "AZPS": "Arizona Public Service", "PSCO": "Xcel Colorado",
    "NEVP": "NV Energy", "PNM": "PNM (New Mexico)", "IPCO": "Idaho Power",
    "PGE": "Portland General", "LGEE": "LG&E and KU", "SCEG": "Dominion SC",
    "TVA": "Tennessee Valley Authority",
    "DOM": "Dominion zone, PJM (N. Virginia)",
}
