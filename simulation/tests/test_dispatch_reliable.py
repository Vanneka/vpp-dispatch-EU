"""The reliable dispatcher: re-send until confirmed, and act on each reply reason."""

import pytest

from vppsim import Ack, AckReason, DeviceTelemetry, InMemoryBroker, OperationError, ValidationError
from vppsim.network import ack_topic, command_topic, telemetry_topic
from vppsim.vpp import DeviceSpec, InMemoryStateStore, ReliableDispatcher, RetryPolicy


def setup(n=2):
    broker, store = InMemoryBroker(), InMemoryStateStore()
    dispatcher = ReliableDispatcher(broker, store, minutes=15)
    sent = []
    broker.subscribe(command_topic("+"), lambda e: sent.append(e.payload))
    for i in range(n):
        device_id = f"b{i}"
        store.enroll(DeviceSpec(device_id, capacity_kwh=10, max_power_kw=5))
        telemetry = DeviceTelemetry(device_id, 0, 0.0, 0.0, soc_kwh=5.0)
        broker.publish(telemetry_topic(device_id), telemetry, step=0)
    broker.deliver(0)
    return broker, dispatcher, sent


def reply(broker, command_id, reason, step=1, version=1):
    device_id = command_id.split("-")[0]
    broker.publish(ack_topic(device_id), Ack(command_id, device_id, version, reason), step)
    broker.deliver(step)


def test_retries_send_the_identical_command():
    broker, dispatcher, sent = setup(n=1)
    dispatcher.dispatch(4.0, step=1)
    assert dispatcher.resend(1, 15) == 1
    broker.deliver(1)
    assert len(sent) == 2 and sent[0] == sent[1]


def test_applied_reply_confirms_and_stops_retries():
    broker, dispatcher, sent = setup()
    dispatcher.dispatch(8.0, step=1)
    broker.deliver(1)
    reply(broker, "b0-v1", AckReason.APPLIED)
    assert dispatcher.resend(1, 15) == 1  # only b1 is still unconfirmed
    assert dispatcher.stats.confirmed == 1


def test_time_to_confirm_counts_from_the_first_send():
    broker, dispatcher, _ = setup(n=1)
    dispatcher.dispatch(4.0, step=1)
    dispatcher.resend(1, 15)
    reply(broker, "b0-v1", AckReason.APPLIED)
    assert dispatcher.stats.confirm_times_s == [15.0]


def test_duplicate_reply_confirms_and_is_counted():
    broker, dispatcher, _ = setup(n=1)
    dispatcher.dispatch(4.0, step=1)
    dispatcher.resend(1, 15)
    reply(broker, "b0-v1", AckReason.DUPLICATE)
    assert dispatcher.stats.confirmed == 1
    assert dispatcher.stats.duplicate_replies == 1
    assert dispatcher.resend(1, 45) == 0


def test_stale_reply_drops_the_command_without_confirming_it():
    broker, dispatcher, _ = setup(n=1)
    dispatcher.dispatch(4.0, step=1)
    reply(broker, "b0-v1", AckReason.STALE)
    assert dispatcher.resend(1, 15) == 0
    assert dispatcher.stats.confirmed == 0


def test_conflict_reply_stops_the_run():
    broker, dispatcher, _ = setup(n=1)
    dispatcher.dispatch(4.0, step=1)
    with pytest.raises(OperationError):
        reply(broker, "b0-v1", AckReason.CONFLICT)


def test_a_newer_command_replaces_an_unconfirmed_one():
    broker, dispatcher, sent = setup(n=1)
    dispatcher.dispatch(4.0, step=1)
    dispatcher.dispatch(-4.0, step=2)
    reply(broker, "b0-v1", AckReason.APPLIED, step=2)  # late reply for the old command
    assert dispatcher.stats.confirmed == 0
    dispatcher.resend(2, 15)
    broker.deliver(2)
    assert sent[-1].command_id == "b0-v2"


def test_an_unconfirmed_command_is_sent_again_next_step():
    broker, dispatcher, sent = setup(n=1)
    dispatcher.dispatch(4.0, step=1)
    dispatcher.dispatch(4.0, step=2)  # same setpoint, still unconfirmed
    broker.deliver(2)
    assert [c.command_id for c in sent] == ["b0-v1", "b0-v1"]


def test_deadline_must_fit_inside_one_step():
    with pytest.raises(ValidationError):
        ReliableDispatcher(
            InMemoryBroker(), InMemoryStateStore(), minutes=15, policy=RetryPolicy(deadline_s=901)
        )
