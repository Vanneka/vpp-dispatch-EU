"""The reliable dispatcher: re-send each command until the battery confirms it."""

from __future__ import annotations

from vppsim.errors import OperationError, fail_validation_if
from vppsim.messages import AckReason, Command
from vppsim.network.message_broker import Envelope, MessageBroker, command_topic
from vppsim.vpp.allocator import allocate
from vppsim.vpp.dispatcher import Dispatcher
from vppsim.vpp.retry_policy import RetryPolicy
from vppsim.vpp.state_store import StateStore


class ReliableDispatcher(Dispatcher):
    """Sends a command when a setpoint changes, then re-sends it until it is confirmed.

    A retry is the identical command (same ID and version), so the control
    unit applies it at most once. A command stays unconfirmed until a reply
    accepts it or a newer command for the same battery replaces it. One still
    unconfirmed at the end of a step is sent again at the start of the next.
    """

    def __init__(
        self,
        broker: MessageBroker,
        store: StateStore,
        *,
        minutes: float,
        policy: RetryPolicy = RetryPolicy(),
    ) -> None:
        super().__init__(broker, store, minutes=minutes)
        fail_validation_if(
            policy.deadline_s > minutes * 60, "the retry deadline must fit inside one step"
        )
        self.policy = policy
        self._versions: dict[str, int] = {}  # last version sent, per device
        self._sent_kw: dict[str, float] = {}  # last setpoint sent, per device
        self._pending: dict[str, Command] = {}  # unconfirmed command, per device
        self._first_sent_s: dict[str, float] = {}  # when each command was first sent
        self._now_s = 0.0  # simulated time: seconds since the first step began

    def dispatch(self, target_kw: float, step: int) -> dict[str, float]:
        """Split the fleet target and send every changed or still unconfirmed command.

        Returns the setpoint the VPP wants for each battery this step.
        """
        self._now_s = step * self.minutes * 60
        setpoints = allocate(target_kw, self.store.all(), minutes=self.minutes)
        for device_id, setpoint_kw in setpoints.items():
            if self._sent_kw.get(device_id, 0.0) == setpoint_kw:
                if device_id in self._pending:
                    self._send(self._pending[device_id], step)  # carried over from last step
                continue
            version = self._versions.get(device_id, 0) + 1
            self._versions[device_id] = version
            self._sent_kw[device_id] = setpoint_kw
            command = Command(f"{device_id}-v{version}", device_id, version, setpoint_kw)
            self._pending[device_id] = command  # replaces any older unconfirmed command
            self._first_sent_s[command.command_id] = self._now_s
            self.stats.commands += 1
            self._send(command, step)
        return setpoints

    def try_times_s(self) -> list[float]:
        """Return the send times from the retry policy: 0, 15, 45, ... seconds."""
        return self.policy.try_times_s()

    def resend(self, step: int, time_s: float) -> int:
        """Re-send every unconfirmed command; return how many were sent."""
        self._now_s = step * self.minutes * 60 + time_s
        for command in self._pending.values():
            self._send(command, step)
        return len(self._pending)

    def _send(self, command: Command, step: int) -> None:
        """Publish one copy of a command."""
        self.broker.publish(command_topic(command.device_id), command, step)
        self.stats.sends += 1

    def _on_ack(self, envelope: Envelope) -> None:
        """Act on a reply: confirm, drop or stop, depending on its reason."""
        ack = envelope.payload
        self.stats.acks += 1
        if ack.reason == AckReason.DUPLICATE:
            self.stats.duplicate_replies += 1
        pending = self._pending.get(ack.device_id)
        if pending is None or pending.command_id != ack.command_id:
            return  # a late reply for a command already confirmed or replaced
        match ack.reason:
            case AckReason.APPLIED | AckReason.DUPLICATE:
                del self._pending[ack.device_id]
                self.stats.confirmed += 1
                first_sent_s = self._first_sent_s.pop(ack.command_id)
                self.stats.confirm_times_s.append(self._now_s - first_sent_s)
            case AckReason.STALE:
                del self._pending[ack.device_id]  # the battery already has a newer command
            case AckReason.CONFLICT:
                raise OperationError(f"two different commands share version {ack.version}")
