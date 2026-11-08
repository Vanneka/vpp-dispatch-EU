"""Load German day-ahead prices from a SMARD export.

Each row of the file is one 15-minute slot, so each row becomes one numbered
step: 0, 1, 2, ... Steps are row numbers, not clock times, so the slots that
appear twice when the clocks go back (2:00 to 2:45 AM) stay separate.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from vppsim.errors import fail_validation_if

DE_LU_COLUMN = "Germany/Luxembourg"  # start of the DE-LU price column's header


@dataclass(frozen=True)
class PricePoint:
    """The day-ahead price for one 15-minute slot."""

    step: int  # 0 for the first slot in the file, then 1, 2, ...
    label: str  # the slot's start time as written in the file, for display only
    eur_per_mwh: float


def load_prices(path: str | Path) -> list[PricePoint]:
    """Read the DE-LU prices from a SMARD CSV file, one PricePoint per row.

    Expects SMARD's English export: semicolon-separated, dates like
    "Oct 24, 2026 6:00 AM" and dot decimals. Raises ValidationError if the
    DE-LU column is missing or a price is empty.
    """
    with open(path, newline="", encoding="utf-8-sig") as file:
        rows = csv.reader(file, delimiter=";")
        header = next(rows, None)
        fail_validation_if(header is None, f"{path} is empty")
        column = next((i for i, name in enumerate(header) if name.startswith(DE_LU_COLUMN)), None)
        fail_validation_if(column is None, f"no {DE_LU_COLUMN} column in {path}")
        points = []
        for step, row in enumerate(rows):
            value = row[column].strip().replace(",", "")  # "," only appears as a thousands mark
            fail_validation_if(value in ("", "-"), f"missing DE-LU price for step {step}")
            points.append(PricePoint(step, row[0], float(value)))
    return points
