"""Splitting the fleet target across batteries."""

import pytest

from vppsim import Battery, DeviceTelemetry
from vppsim.vpp import DeviceSpec, DeviceView, allocate, deliverable_kw

SLOT = 15


def view(device_id: str, soc: float | None, capacity=10.0, power=5.0, reserve=0.0) -> DeviceView:
    spec = DeviceSpec(device_id, capacity_kwh=capacity, max_power_kw=power, min_soc_kwh=reserve)
    if soc is None:
        return DeviceView(spec)
    reported = DeviceTelemetry(
        device_id, applied_version=0, setpoint_kw=0, delivered_kw=0, soc_kwh=soc
    )
    return DeviceView(spec, reported, reported_step=0)


def test_split_is_proportional_to_what_each_can_deliver():
    views = [view("big", 5.0, power=6.0), view("small", 5.0, power=3.0)]
    setpoints = allocate(6.0, views, minutes=SLOT)
    assert setpoints == {"big": pytest.approx(4.0), "small": pytest.approx(2.0)}


def test_setpoints_add_up_to_the_target():
    views = [view(f"b{i}", 5.0, power=p) for i, p in enumerate([3.0, 5.0, 5.0])]
    assert sum(allocate(-9.0, views, minutes=SLOT).values()) == pytest.approx(-9.0, abs=0.03)


def test_target_above_fleet_capacity_asks_everyone_for_their_maximum():
    views = [view("a", 5.0, power=5.0), view("b", 5.0, power=3.0)]
    assert allocate(100.0, views, minutes=SLOT) == {"a": 5.0, "b": 3.0}


def test_battery_at_its_reserve_gets_nothing_to_discharge():
    views = [view("low", 2.0, reserve=2.0), view("ok", 5.0)]
    assert allocate(4.0, views, minutes=SLOT) == {"low": 0.0, "ok": 4.0}


def test_full_battery_gets_nothing_to_charge():
    views = [view("full", 10.0), view("ok", 5.0)]
    assert allocate(-4.0, views, minutes=SLOT) == {"full": 0.0, "ok": -4.0}


def test_battery_without_a_report_gets_nothing():
    views = [view("silent", None), view("ok", 5.0)]
    assert allocate(4.0, views, minutes=SLOT) == {"silent": 0.0, "ok": 4.0}


def test_zero_target_means_everyone_idle():
    assert allocate(0.0, [view("a", 5.0), view("b", 5.0)], minutes=SLOT) == {"a": 0.0, "b": 0.0}


def test_setpoints_never_exceed_what_the_battery_can_do():
    v = view("b", 3.0, power=5.0, reserve=2.0)  # 1 kWh usable: at most 3.8 kW
    setpoint = allocate(100.0, [v], minutes=SLOT)["b"]
    assert setpoint <= deliverable_kw(v, discharging=True, minutes=SLOT)
    assert setpoint == pytest.approx(3.8)


def test_vpp_estimate_matches_the_battery_when_the_report_is_current():
    battery = Battery("b", capacity_kwh=10, max_power_kw=5, soc_kwh=3, min_soc_kwh=2)
    v = view("b", battery.soc_kwh, reserve=2.0)
    _, real_discharge = battery.available_power(minutes=SLOT)
    assert deliverable_kw(v, discharging=True, minutes=SLOT) == real_discharge
