"""The naive dispatcher: send each command once and never check that it arrived."""

from __future__ import annotations

from vppsim.messages import Command
from vppsim.network.message_broker import Envelope, MessageBroker, command_topic
from vppsim.vpp.allocator import allocate
from vppsim.vpp.dispatcher import Dispatcher
from vppsim.vpp.state_store import StateStore


class NaiveDispatcher(Dispatcher):
    """Sends a battery a command only when its setpoint changes, and never retries.

    It counts the replies it gets, so it can be compared with the reliable
    dispatcher, but never acts on them: if a command is lost, the battery
    keeps its old setpoint until the next change.
    """

    def __init__(self, broker: MessageBroker, store: StateStore, *, minutes: float) -> None:
        super().__init__(broker, store, minutes=minutes)
        self._versions: dict[str, int] = {}  # last version sent, per device
        self._sent_kw: dict[str, float] = {}  # last setpoint sent, per device
        self._confirmed: set[str] = set()  # IDs of commands with an accepted reply

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
            self.stats.commands += 1
            self.stats.sends += 1
        return setpoints

    def try_times_s(self) -> list[float]:
        """Return only the start of the step: the naive dispatcher sends once."""
        return [0.0]

    def resend(self, step: int, time_s: float) -> int:
        """Send nothing: the naive dispatcher never retries."""
        return 0

    def _on_ack(self, envelope: Envelope) -> None:
        """Count a reply; the naive dispatcher does nothing else with it."""
        ack = envelope.payload
        self.stats.acks += 1
        if ack.accepted and ack.command_id not in self._confirmed:
            self._confirmed.add(ack.command_id)
            self.stats.confirmed += 1
            self.stats.confirm_times_s.append(0.0)  # replies arrive in the same round
