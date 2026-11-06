"""The DER base class: physics only, no VPP behaviour."""

import pytest

from vppsim import Battery, DistributedEnergyResource, ValidationError


def test_base_class_cannot_be_instantiated():
    with pytest.raises(TypeError):
        DistributedEnergyResource("x")


def test_unenrolled_battery_runs_on_its_own_setpoint():
    b = Battery("b1", capacity_kwh=10, max_power_kw=5, soc_kwh=5)
    b.setpoint_kw = 2.0
    assert b.step(15) == pytest.approx(2.0)
    assert not hasattr(b, "handle_command")  # no VPP behaviour without a control unit


def test_empty_device_id_rejected():
    with pytest.raises(ValidationError):
        Battery("", capacity_kwh=10, max_power_kw=5, soc_kwh=5)
