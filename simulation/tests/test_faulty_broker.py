"""The faulty broker: loss, duplication, and the same faults in every run."""

import pytest

from vppsim import Ack, AckReason, Command, DeviceTelemetry, ValidationError
from vppsim.network import (
    FaultConfig,
    FaultyBroker,
    InMemoryBroker,
    command_topic,
    message_identity,
)


def cmd(i: int) -> Command:
    return Command(f"c{i}", "b1", version=i + 1, setpoint_kw=1.0)


def delivered_ids(broker, commands, extra_between=0) -> list[str]:
    """Send commands, optionally with unrelated traffic in between, and list what arrived."""
    got = []
    broker.subscribe(command_topic("b1"), lambda e: got.append(e.payload.command_id))
    for c in commands:
        broker.publish(command_topic("b1"), c, step=0)
        for k in range(extra_between):
            broker.publish(
                command_topic("other"), Command(f"x{c.command_id}-{k}", "other", 1, 0.0), step=0
            )
    broker.deliver(0)
    return got


def test_no_faults_behaves_like_perfect_broker():
    commands = [cmd(i) for i in range(50)]
    assert delivered_ids(FaultyBroker(seed=1), commands) == delivered_ids(
        InMemoryBroker(), commands
    )


def test_full_loss_drops_everything():
    broker = FaultyBroker(seed=1, down=FaultConfig(loss=1.0))
    assert delivered_ids(broker, [cmd(i) for i in range(20)]) == []
    assert broker.stats.lost == 20


def test_full_duplication_delivers_everything_twice():
    broker = FaultyBroker(seed=1, down=FaultConfig(duplicate=1.0))
    got = delivered_ids(broker, [cmd(i) for i in range(10)])
    assert len(got) == 20 and set(got) == {f"c{i}" for i in range(10)}


def test_same_seed_gives_same_faults_despite_other_traffic():
    """The fairness rule: extra messages (like retries) must not change other messages' fates."""
    commands = [cmd(i) for i in range(200)]
    faults = FaultConfig(loss=0.3, duplicate=0.2)
    quiet = delivered_ids(FaultyBroker(seed=7, down=faults), commands)
    brokery = delivered_ids(FaultyBroker(seed=7, down=faults), commands, extra_between=3)
    assert quiet == brokery


def test_different_seed_gives_different_faults():
    commands = [cmd(i) for i in range(200)]
    faults = FaultConfig(loss=0.3)
    a = delivered_ids(FaultyBroker(seed=1, down=faults), commands)
    b = delivered_ids(FaultyBroker(seed=2, down=faults), commands)
    assert a != b


def test_retry_gets_its_own_chance():
    broker = FaultyBroker(seed=3, down=FaultConfig(loss=0.5))
    commands = [cmd(i) for i in range(400)]
    first = set(delivered_ids(broker, commands))
    second = []
    broker.subscribe(command_topic("b1"), lambda e: second.append(e.payload.command_id))
    for c in commands:
        if c.command_id not in first:
            broker.publish(command_topic("b1"), c, step=1)  # identical command = retry
    broker.deliver(1)
    lost_first = 400 - len(first)
    assert 0 < len(set(second)) < lost_first  # some retries get through, some are lost again
    assert broker.attempts(command_topic("b1"), "c0") in (1, 2)


def test_loss_rate_roughly_matches_setting():
    broker = FaultyBroker(seed=11, down=FaultConfig(loss=0.1))
    delivered_ids(broker, [cmd(i) for i in range(10_000)])
    assert broker.stats.lost / broker.stats.published == pytest.approx(0.1, abs=0.015)


def test_up_and_down_directions_are_configured_separately():
    broker = FaultyBroker(seed=1, down=FaultConfig(), up=FaultConfig(loss=1.0))
    broker.publish(command_topic("b1"), cmd(1), step=0)  # a command goes down: kept
    broker.publish("vpp/der/b1/ack", Ack("c1", "b1", 1, AckReason.APPLIED), step=0)  # up: lost
    assert broker.stats.lost == 1 and broker.pending() == 1


def test_counters_add_up():
    broker = FaultyBroker(seed=5, down=FaultConfig(loss=0.2, duplicate=0.2))
    delivered_ids(broker, [cmd(i) for i in range(500)])
    s = broker.stats
    assert s.delivered + s.lost == s.published + s.duplicated


def test_telemetry_identity_uses_device_and_step():
    t = DeviceTelemetry("b1", applied_version=1, setpoint_kw=1.0, delivered_kw=1.0)
    assert message_identity(t, step=40) == "b1@40"
    assert message_identity(cmd(3), step=40) == "c3"


@pytest.mark.parametrize("kwargs", [dict(loss=-0.1), dict(loss=1.5), dict(duplicate=2.0)])
def test_invalid_fault_shares_rejected(kwargs):
    with pytest.raises(ValidationError):
        FaultConfig(**kwargs)


def test_unknown_message_type_rejected():
    with pytest.raises(TypeError):
        message_identity("not a message", step=0)


def test_fault_type_values_are_stable():
    """The values feed the fault calculation, so changing them changes every result."""
    from vppsim.network import FaultType

    assert [f.value for f in FaultType] == ["lost", "duplicated"]
