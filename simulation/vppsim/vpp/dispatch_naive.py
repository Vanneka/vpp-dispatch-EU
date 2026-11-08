"""The naive dispatcher: send each command once and never check that it arrived."""

from __future__ import annotations

from vppsim.messages import Command
from vppsim.network.message_broker import (
    Envelope,
    MessageBroker,
    ack_topic,
    command_topic,
    telemetry_topic,
)
from vppsim.vpp.allocator import allocate
from vppsim.vpp.state_store import StateStore


class NaiveDispatcher:
    """Sends a battery a command only when its setpoint changes, and never retries.

    It listens to the batteries' reports to keep the state store up to date,
    but only counts their replies: if a command is lost, the battery keeps
    its old setpoint until the next change.
    """

    def __init__(self, broker: MessageBroker, store: StateStore, *, minutes: float) -> None:
        self.broker = broker
        self.store = store
        self.minutes = minutes
        self.acks_received = 0
        self._versions: dict[str, int] = {}  # last version sent, per device
        self._sent_kw: dict[str, float] = {}  # last setpoint sent, per device
        broker.subscribe(telemetry_topic("+"), self._on_telemetry)
        broker.subscribe(ack_topic("+"), self._on_ack)

    def dispatch(self, target_kw: float, step: int) -> dict[str, float]:
        """Split the fleet target and send a command to every battery whose setpoint changed.

        Returns the setpoint the VPP wants for each battery this step.
        """
        setpoints = allocate(target_kw, self.store.all(), minutes=self.minutes)
        for device_id, setpoint_kw in setpoints.items():
            if self._sent_kw.get(device_id, 0.0) == setpoint_kw:
                continue  # unchanged (batteries start idle at 0 kW): nothing to send
            version = self._versions.get(device_id, 0) + 1
            self._versions[device_id] = version
            self._sent_kw[device_id] = setpoint_kw
            command = Command(f"{device_id}-v{version}", device_id, version, setpoint_kw)
            self.broker.publish(command_topic(device_id), command, step)
        return setpoints

    def _on_telemetry(self, envelope: Envelope) -> None:
        """Record a battery's report in the state store."""
        self.store.update_reported(envelope.payload, envelope.sent_step)

    def _on_ack(self, envelope: Envelope) -> None:
        """Count a reply; the naive dispatcher does nothing else with it."""
        self.acks_received += 1
