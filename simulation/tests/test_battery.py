"""Battery physics: limits, state of charge and losses."""

import pytest

from vppsim import Battery, ValidationError

SLOT = 15  # minutes: one simulation step


def test_worked_example_discharge_with_losses():
    b = Battery("b1", capacity_kwh=10, max_power_kw=5, soc_kwh=6)
    b.setpoint_kw = 4.0
    assert b.run_for(minutes=SLOT) == pytest.approx(4.0)  # 4 kW for 0.25 h = 1 kWh to the grid
    assert b.soc_kwh == pytest.approx(6 - 1 / 0.95)


def test_charge_with_losses():
    b = Battery("b1", capacity_kwh=10, max_power_kw=5, soc_kwh=2)
    b.setpoint_kw = -4.0
    assert b.run_for(minutes=SLOT) == pytest.approx(-4.0)
    assert b.soc_kwh == pytest.approx(2 + 1 * 0.95)


def test_power_limit_respected_both_directions():
    b = Battery("b1", capacity_kwh=10, max_power_kw=5, soc_kwh=5)
    b.setpoint_kw = 8.0
    assert b.run_for(minutes=SLOT) == pytest.approx(5.0)
    b.setpoint_kw = -8.0
    assert b.run_for(minutes=SLOT) == pytest.approx(-5.0)


def test_nearly_empty_battery_delivers_only_what_it_has():
    b = Battery("b1", capacity_kwh=10, max_power_kw=5, soc_kwh=0.5)
    b.setpoint_kw = 4.0
    assert b.run_for(minutes=SLOT) == pytest.approx(0.5 * 0.95 / 0.25)
    assert b.soc_kwh == pytest.approx(0.0)


def test_empty_cannot_discharge_and_full_cannot_charge():
    empty = Battery("b1", capacity_kwh=10, max_power_kw=5, soc_kwh=0)
    empty.setpoint_kw = 3.0
    assert empty.run_for(minutes=SLOT) == 0.0
    full = Battery("b2", capacity_kwh=10, max_power_kw=5, soc_kwh=10)
    full.setpoint_kw = -3.0
    assert full.run_for(minutes=SLOT) == 0.0


def test_soc_stays_within_bounds_over_many_steps():
    b = Battery("b1", capacity_kwh=10, max_power_kw=5, soc_kwh=5)
    for i in range(400):
        b.setpoint_kw = 5.0 if (i // 20) % 2 == 0 else -5.0
        b.run_for(minutes=SLOT)
        assert 0.0 <= b.soc_kwh <= 10.0


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(capacity_kwh=0, max_power_kw=5, soc_kwh=0),
        dict(capacity_kwh=10, max_power_kw=0, soc_kwh=5),
        dict(capacity_kwh=10, max_power_kw=5, soc_kwh=11),
        dict(capacity_kwh=10, max_power_kw=5, soc_kwh=5, charge_efficiency=1.2),
    ],
)
def test_invalid_parameters_rejected(kwargs):
    with pytest.raises(ValidationError):
        Battery("b1", **kwargs)
