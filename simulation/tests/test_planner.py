"""Planning: charge in the cheapest slots, discharge in the most expensive."""

import pytest

from vppsim import ValidationError
from vppsim.market import PricePoint
from vppsim.vpp import plan


def prices(values):
    return [PricePoint(i, f"slot {i}", v) for i, v in enumerate(values)]


def test_cheapest_charge_and_dearest_discharge():
    targets = plan(prices([50, 10, 90, 20, 80, 60]), fleet_power_kw=100, slots=2, block=6)
    assert targets == [0, -100, 100, -100, 100, 0]


def test_slots_are_counted_per_block():
    values = [1, 2, 3, 4] * 3
    targets = plan(prices(values), fleet_power_kw=10, slots=1, block=4)
    assert targets == [-10, 0, 0, 10] * 3


def test_short_final_block_uses_fewer_slots():
    targets = plan(prices([1, 2, 3, 4, 5, 6, 7]), fleet_power_kw=10, slots=2, block=4)
    assert targets[4:] == [-10, 0, 10]  # 3 left: only 1 slot each way


def test_equal_prices_are_decided_by_order():
    targets = plan(prices([5, 5, 5, 5]), fleet_power_kw=10, slots=1, block=4)
    assert targets == [-10, 0, 0, 10]


@pytest.mark.parametrize("kwargs", [dict(fleet_power_kw=0), dict(slots=-1), dict(slots=3, block=4)])
def test_invalid_settings_rejected(kwargs):
    settings = dict(fleet_power_kw=10, slots=1, block=4) | kwargs
    with pytest.raises(ValidationError):
        plan(prices([1, 2, 3, 4]), **settings)
