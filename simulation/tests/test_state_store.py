"""The VPP's picture of each battery."""

import pytest

from vppsim import DeviceTelemetry, RoutingError, ValidationError
from vppsim.vpp import DeviceSpec, InMemoryStateStore


def report(soc: float, device_id: str = "b1") -> DeviceTelemetry:
    return DeviceTelemetry(device_id, applied_version=0, setpoint_kw=0, delivered_kw=0, soc_kwh=soc)


def test_enrolled_device_has_no_report_yet():
    store = InMemoryStateStore()
    store.enroll(DeviceSpec("b1", capacity_kwh=10, max_power_kw=5))
    view = store.get("b1")
    assert view.reported is None and view.reported_step is None


def test_newest_report_is_kept():
    store = InMemoryStateStore()
    store.enroll(DeviceSpec("b1", capacity_kwh=10, max_power_kw=5))
    store.update_reported(report(5.0), step=3)
    store.update_reported(report(4.0), step=4)
    assert store.get("b1").reported.soc_kwh == 4.0 and store.get("b1").reported_step == 4


def test_older_report_arriving_late_is_ignored():
    store = InMemoryStateStore()
    store.enroll(DeviceSpec("b1", capacity_kwh=10, max_power_kw=5))
    store.update_reported(report(4.0), step=4)
    store.update_reported(report(5.0), step=3)
    assert store.get("b1").reported.soc_kwh == 4.0


def test_all_returns_devices_in_enrollment_order():
    store = InMemoryStateStore()
    for name in ["b2", "b1", "b3"]:
        store.enroll(DeviceSpec(name, capacity_kwh=10, max_power_kw=5))
    assert [v.device_id for v in store.all()] == ["b2", "b1", "b3"]


def test_enrolling_twice_rejected():
    store = InMemoryStateStore()
    store.enroll(DeviceSpec("b1", capacity_kwh=10, max_power_kw=5))
    with pytest.raises(ValidationError):
        store.enroll(DeviceSpec("b1", capacity_kwh=10, max_power_kw=5))


def test_report_from_unknown_device_is_a_routing_error():
    with pytest.raises(RoutingError):
        InMemoryStateStore().update_reported(report(5.0, "b9"), step=0)
