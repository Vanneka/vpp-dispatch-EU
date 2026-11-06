"""The perfect broker: topics, subscriptions and delivery order."""

import pytest

from vppsim import Command, ValidationError
from vppsim.network import InMemoryBroker, ack_topic, command_topic, telemetry_topic, topic_matches


def cmd(command_id: str, device_id: str = "b1", version: int = 1) -> Command:
    return Command(command_id, device_id, version, setpoint_kw=1.0)


def test_topic_helpers():
    assert command_topic("b1") == "vpp/der/b1/cmd"
    assert ack_topic("b1") == "vpp/der/b1/ack"
    assert telemetry_topic("b1") == "vpp/der/b1/telemetry"


@pytest.mark.parametrize(
    "pattern, topic, expected",
    [
        ("vpp/der/b1/cmd", "vpp/der/b1/cmd", True),
        ("vpp/der/+/ack", "vpp/der/b7/ack", True),
        ("vpp/der/+/ack", "vpp/der/b7/cmd", False),
        ("vpp/der/+", "vpp/der/b7/ack", False),  # "+" matches exactly one part
    ],
)
def test_topic_matching(pattern, topic, expected):
    assert topic_matches(pattern, topic) is expected


def test_message_arrives_only_after_deliver():
    broker, got = InMemoryBroker(), []
    broker.subscribe(command_topic("b1"), got.append)
    broker.publish(command_topic("b1"), cmd("c1"), step=0)
    assert got == []
    assert broker.deliver(0) == 1
    assert [e.payload.command_id for e in got] == ["c1"]


def test_each_message_delivered_once_in_send_order():
    broker, got = InMemoryBroker(), []
    broker.subscribe("vpp/der/+/cmd", got.append)
    for i in range(5):
        broker.publish(command_topic("b1"), cmd(f"c{i}"), step=0)
    broker.deliver(0)
    broker.deliver(0)  # nothing left to deliver
    assert [e.payload.command_id for e in got] == [f"c{i}" for i in range(5)]


def test_only_matching_subscribers_receive():
    broker, b1, b2 = InMemoryBroker(), [], []
    broker.subscribe(command_topic("b1"), b1.append)
    broker.subscribe(command_topic("b2"), b2.append)
    broker.publish(command_topic("b1"), cmd("c1", "b1"), step=0)
    broker.deliver(0)
    assert len(b1) == 1 and b2 == []


def test_message_without_subscriber_is_counted_as_unrouted():
    broker = InMemoryBroker()
    broker.publish(command_topic("b1"), cmd("c1"), step=0)
    broker.deliver(0)
    assert broker.stats.unrouted == 1


def test_messages_sent_during_delivery_wait_for_next_deliver():
    broker, acks = InMemoryBroker(), []
    broker.subscribe(
        command_topic("b1"), lambda e: broker.publish(ack_topic("b1"), e.payload, step=0)
    )
    broker.subscribe(ack_topic("b1"), acks.append)
    broker.publish(command_topic("b1"), cmd("c1"), step=0)
    broker.deliver(0)
    assert acks == [] and broker.pending() == 1
    broker.deliver(0)
    assert len(acks) == 1


def test_negative_step_rejected():
    with pytest.raises(ValidationError):
        InMemoryBroker().publish(command_topic("b1"), cmd("c1"), step=-1)
