"""VPP participation: applying commands at most once, and telemetry."""

import pytest

from vppsim import Ack, AckReason, Battery, Command, ControlUnit, RoutingError, ValidationError


def make_unit() -> ControlUnit:
    return ControlUnit(Battery("b1", capacity_kwh=10, max_power_kw=5, soc_kwh=5))


def test_newer_version_is_applied():
    unit = make_unit()
    ack = unit.handle_command(Command("c1", "b1", version=1, setpoint_kw=2.0))
    assert ack.accepted and ack.reason == AckReason.APPLIED
    assert unit.der.setpoint_kw == 2.0
    assert unit.applied_version == 1 and unit.last_applied_command_id == "c1"


def test_update_with_higher_version_replaces_setpoint():
    unit = make_unit()
    unit.handle_command(Command("c1", "b1", version=1, setpoint_kw=4.0))
    unit.handle_command(Command("c2", "b1", version=2, setpoint_kw=2.0))
    assert unit.der.setpoint_kw == 2.0


def test_retry_of_latest_command_is_reacked_not_reapplied():
    unit = make_unit()
    cmd = Command("c1", "b1", version=1, setpoint_kw=2.0)
    unit.handle_command(cmd)
    unit.der.setpoint_kw = 0.0  # if the retry were re-applied, this would change back to 2.0
    ack = unit.handle_command(cmd)
    assert ack.accepted and ack.reason == AckReason.DUPLICATE
    assert unit.der.setpoint_kw == 0.0


def test_late_older_command_is_stale_and_ignored():
    unit = make_unit()
    unit.handle_command(Command("c2", "b1", version=2, setpoint_kw=2.0))
    ack = unit.handle_command(Command("c1", "b1", version=1, setpoint_kw=4.0))  # arrives late
    assert not ack.accepted and ack.reason == AckReason.STALE
    assert unit.der.setpoint_kw == 2.0 and unit.applied_version == 2


def test_older_duplicate_is_also_stale():
    unit = make_unit()
    first = Command("c1", "b1", version=1, setpoint_kw=4.0)
    unit.handle_command(first)
    unit.handle_command(Command("c2", "b1", version=2, setpoint_kw=2.0))
    assert unit.handle_command(first).reason == AckReason.STALE


def test_same_version_different_id_is_a_conflict():
    unit = make_unit()
    unit.handle_command(Command("c1", "b1", version=1, setpoint_kw=2.0))
    ack = unit.handle_command(Command("c9", "b1", version=1, setpoint_kw=-3.0))
    assert not ack.accepted and ack.reason == AckReason.CONFLICT
    assert unit.der.setpoint_kw == 2.0


def test_vpp_restarting_its_numbering_loses_control():
    """Why the VPP must keep its version counter in its command log (Phase 2)."""
    unit = make_unit()
    unit.handle_command(Command("c50", "b1", version=50, setpoint_kw=2.0))
    ack = unit.handle_command(Command("new-c1", "b1", version=1, setpoint_kw=-4.0))
    assert ack.reason == AckReason.STALE
    assert unit.der.setpoint_kw == 2.0  # the restarted VPP's instruction never takes effect


def test_device_keeps_last_setpoint_until_a_newer_command_arrives():
    unit = make_unit()
    unit.handle_command(Command("c1", "b1", 1, 2.0))
    for _ in range(3):  # no new commands for three intervals, e.g. because they were lost
        assert unit.der.run_for(minutes=15) == pytest.approx(2.0)


def test_command_for_other_device_is_a_routing_error():
    with pytest.raises(RoutingError):
        make_unit().handle_command(Command("c1", "b2", 1, 2.0))


def test_telemetry_reports_device_state():
    unit = make_unit()
    unit.handle_command(Command("c1", "b1", 1, 4.0))
    unit.der.run_for(minutes=15)
    t = unit.telemetry()
    assert t.applied_version == 1 and t.delivered_kw == 4.0
    assert t.soc_kwh == pytest.approx(unit.der.soc_kwh)


def test_ack_reason_values_match_the_contract():
    """The values are part of contracts/ack.schema.json, shared with the Phase 3 C# service."""
    assert [r.value for r in AckReason] == ["applied", "duplicate", "stale", "conflict"]


def test_accepted_follows_the_reason():
    assert Ack("c1", "b1", 1, AckReason.APPLIED).accepted
    assert Ack("c1", "b1", 1, AckReason.DUPLICATE).accepted
    assert not Ack("c1", "b1", 1, AckReason.STALE).accepted
    assert not Ack("c1", "b1", 1, AckReason.CONFLICT).accepted


@pytest.mark.parametrize(
    "kwargs", [dict(command_id="", version=1), dict(command_id="c1", version=0)]
)
def test_invalid_command_rejected(kwargs):
    with pytest.raises(ValidationError):
        Command(device_id="b1", setpoint_kw=1.0, **kwargs)
