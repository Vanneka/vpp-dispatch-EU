"""What every dispatcher shares: how it is driven, and the numbers it keeps."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from vppsim.network.message_broker import Envelope, MessageBroker, ack_topic, telemetry_topic
from vppsim.vpp.state_store import StateStore


@dataclass
class DispatchStats:
    """What happened to the commands one dispatcher sent."""

    commands: int = 0  # different commands (new setpoints)
    sends: int = 0  # copies sent, retries included
    acks: int = 0  # replies received, of any kind
    confirmed: int = 0  # commands the VPP knows were applied
    unnecessary_retries: int = 0  # DUPLICATE replies: a copy reached a device that had it already
    confirm_times_s: list[float] = field(default_factory=list)  # first send to confirmation


class Dispatcher(ABC):
    """Sends the fleet's setpoints to the batteries, step by step.

    The simulation drives it the same way for every kind: `dispatch` at the
    start of a step, then `resend` at each of `try_times_s` after the first.
    Battery reports go straight to the state store; what to do with a reply
    is up to each kind.
    """

    def __init__(self, broker: MessageBroker, store: StateStore, *, minutes: float) -> None:
        self.broker = broker
        self.store = store
        self.minutes = minutes
        self.stats = DispatchStats()
        broker.subscribe(telemetry_topic("+"), self._on_telemetry)
        broker.subscribe(ack_topic("+"), self._on_ack)

    @abstractmethod
    def dispatch(self, target_kw: float, step: int) -> dict[str, float]:
        """Split the fleet target, send the commands, and return each battery's setpoint."""

    @abstractmethod
    def try_times_s(self) -> list[float]:
        """Return the seconds into a step at which this dispatcher may send: 0 first."""

    @abstractmethod
    def resend(self, step: int, time_s: float) -> int:
        """Re-send what is still unconfirmed at this time in the step; return how many."""

    @abstractmethod
    def _on_ack(self, envelope: Envelope) -> None:
        """Handle a reply from a control unit."""

    def _on_telemetry(self, envelope: Envelope) -> None:
        """Record a battery's report in the state store."""
        self.store.update_reported(envelope.payload, envelope.sent_step)
