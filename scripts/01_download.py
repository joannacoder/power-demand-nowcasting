"""Download EIA-930 demand and Open-Meteo weather for the BA universe."""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pdn import eia930, weather  # noqa: E402

if __name__ == "__main__":
    today = date.today()
    print("EIA-930 ...")
    eia930.download(last_year=today.year)
    print("Weather ...")
    weather.download(end=str(today - timedelta(days=7)))
