"""The naive dispatcher: commands on change only, no retries."""

from vppsim import DeviceTelemetry, InMemoryBroker
from vppsim.network import command_topic, telemetry_topic
from vppsim.vpp import DeviceSpec, InMemoryStateStore, NaiveDispatcher


def setup(n=2):
    broker, store = InMemoryBroker(), InMemoryStateStore()
    dispatcher = NaiveDispatcher(broker, store, minutes=15)
    sent = []
    broker.subscribe(command_topic("+"), lambda e: sent.append(e.payload))
    for i in range(n):
        device_id = f"b{i}"
        store.enroll(DeviceSpec(device_id, capacity_kwh=10, max_power_kw=5))
        telemetry = DeviceTelemetry(device_id, 0, 0.0, 0.0, soc_kwh=5.0)
        broker.publish(telemetry_topic(device_id), telemetry, step=0)
    broker.deliver(0)
    return broker, store, dispatcher, sent


def test_telemetry_updates_the_store():
    _, store, _, _ = setup()
    assert store.get("b0").reported.soc_kwh == 5.0


def test_one_command_per_changed_battery():
    broker, _, dispatcher, sent = setup()
    dispatcher.dispatch(8.0, step=1)
    broker.deliver(1)
    assert sorted(c.device_id for c in sent) == ["b0", "b1"]
    assert all(c.version == 1 and c.setpoint_kw == 4.0 for c in sent)


def test_nothing_is_sent_when_setpoints_do_not_change():
    broker, _, dispatcher, sent = setup()
    dispatcher.dispatch(8.0, step=1)
    dispatcher.dispatch(8.0, step=2)
    broker.deliver(2)
    assert len(sent) == 2


def test_idle_start_sends_nothing():
    broker, _, dispatcher, sent = setup()
    dispatcher.dispatch(0.0, step=1)
    broker.deliver(1)
    assert sent == []


def test_versions_increase_per_device():
    broker, _, dispatcher, sent = setup(n=1)
    dispatcher.dispatch(4.0, step=1)
    dispatcher.dispatch(-4.0, step=2)
    broker.deliver(2)
    assert [(c.command_id, c.version) for c in sent] == [("b0-v1", 1), ("b0-v2", 2)]


def test_acks_are_counted_but_cause_no_resend():
    broker, _, dispatcher, sent = setup(n=1)
    dispatcher.dispatch(4.0, step=1)
    broker.deliver(1)
    from vppsim import Ack, AckReason
    from vppsim.network import ack_topic

    broker.publish(ack_topic("b0"), Ack("b0-v1", "b0", 1, AckReason.APPLIED), step=1)
    broker.deliver(1)
    assert dispatcher.acks_received == 1 and len(sent) == 1
