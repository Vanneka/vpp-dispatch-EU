"""Loading SMARD prices."""

from pathlib import Path

import pytest

from vppsim import ValidationError
from vppsim.market import load_prices

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
SMARD_FILE = next(DATA_DIR.glob("Day-ahead_prices_*Quarterhour.csv"))

HEADER = "Start date;End date;Germany/Luxembourg [€/MWh] Original resolutions;Belgium [€/MWh]\n"


def write(tmp_path, text: str) -> Path:
    path = tmp_path / "prices.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_real_file_loads_every_slot_as_a_numbered_step():
    prices = load_prices(SMARD_FILE)
    assert len(prices) == 1060
    assert [p.step for p in prices] == list(range(1060))
    assert prices[0].eur_per_mwh == 15.38
    assert prices[0].label == "Oct 24, 2026 6:00 AM"


def test_clock_change_slots_stay_separate():
    prices = load_prices(SMARD_FILE)
    repeated = [p for p in prices if p.label == "Oct 25, 2026 2:00 AM"]
    assert len(repeated) == 2
    assert repeated[0].step != repeated[1].step


def test_reads_the_de_lu_column_not_its_neighbours(tmp_path):
    path = write(tmp_path, HEADER + "Oct 24, 2026 6:00 AM;Oct 24, 2026 6:15 AM;15.38;99.00\n")
    assert load_prices(path)[0].eur_per_mwh == 15.38


def test_thousands_mark_is_handled(tmp_path):
    path = write(tmp_path, HEADER + "a;b;1,234.50;1.00\n")
    assert load_prices(path)[0].eur_per_mwh == 1234.5


def test_missing_column_rejected(tmp_path):
    path = write(tmp_path, "Start date;End date;Belgium [€/MWh]\na;b;1.0\n")
    with pytest.raises(ValidationError):
        load_prices(path)


def test_missing_price_rejected(tmp_path):
    path = write(tmp_path, HEADER + "a;b;-;1.0\n")
    with pytest.raises(ValidationError):
        load_prices(path)
