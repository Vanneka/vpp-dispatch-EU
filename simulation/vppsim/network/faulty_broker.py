"""The faulty broker: the broker plus an unreliable network around it.

Every fault is decided from the message's identity, not from a running
random sequence: outcome = f(seed, topic, message identity, fault type,
attempt). So the same message meets the same fate in every run with the same
seed, no matter how many other messages are sent. This lets the naive and
reliable dispatchers be compared under exactly the same faults, while a
retry (a new attempt) gets its own, independent chance.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum

from vppsim.errors import fail_validation_if
from vppsim.messages import Ack, Command, DeviceTelemetry
from vppsim.network.in_memory_broker import InMemoryBroker
from vppsim.network.message_broker import Message


class FaultType(str, Enum):
    """The kinds of fault the broker can cause to a message."""

    LOST = "lost"
    DUPLICATED = "duplicated"


@dataclass(frozen=True)
class FaultConfig:
    """How often each fault happens in one direction, as a share from 0.0 to 1.0."""

    loss: float = 0.0  # chance a message never arrives
    duplicate: float = 0.0  # chance a message arrives twice

    def __post_init__(self) -> None:
        """Reject shares outside 0.0 to 1.0."""
        fail_validation_if(not 0.0 <= self.loss <= 1.0, "loss must be between 0 and 1")
        fail_validation_if(not 0.0 <= self.duplicate <= 1.0, "duplicate must be between 0 and 1")


def message_identity(payload: Message, step: int) -> str:
    """Name a message so that a resend of the same message gets the same name.

    Commands and acks are named by their command ID. Telemetry has no ID,
    so it is named by its device and the step it was sent in.
    """
    match payload:
        case Command(command_id=command_id) | Ack(command_id=command_id):
            return command_id
        case DeviceTelemetry(device_id=device_id):
            return f"{device_id}@{step}"
        case _:
            raise TypeError(f"unknown message type {type(payload).__name__}")


class FaultyBroker(InMemoryBroker):
    """A broker that loses and duplicates messages, the same way in every run.

    `down` sets the faults for commands (VPP to devices); `up` sets them for
    acks and telemetry (devices to VPP); the direction follows the message
    type. Create a new broker for every run, so attempt counts do not carry
    over between runs.
    """

    def __init__(
        self,
        seed: int,
        down: FaultConfig = FaultConfig(),
        up: FaultConfig = FaultConfig(),
    ) -> None:
        super().__init__()
        self.seed = seed
        self.down = down
        self.up = up
        self._attempts: defaultdict[tuple[str, str], int] = defaultdict(int)

    def publish(self, topic: str, payload: Message, step: int) -> None:
        """Send a message through the faulty network: it may be lost or duplicated."""
        fail_validation_if(step < 0, "step must not be negative")
        self.stats.published += 1
        identity = message_identity(payload, step)
        attempt = self._attempts[(topic, identity)]
        self._attempts[(topic, identity)] += 1
        faults = self.down if isinstance(payload, Command) else self.up

        if self._chance(topic, identity, FaultType.LOST, attempt) < faults.loss:
            self.stats.lost += 1
            return
        self._enqueue(topic, payload, sent_step=step, deliver_step=step)
        if self._chance(topic, identity, FaultType.DUPLICATED, attempt) < faults.duplicate:
            self.stats.duplicated += 1
            self._enqueue(topic, payload, sent_step=step, deliver_step=step)

    def attempts(self, topic: str, identity: str) -> int:
        """Return how many times a message with this identity was sent on this topic."""
        return self._attempts.get((topic, identity), 0)

    def _chance(self, topic: str, identity: str, fault: FaultType, attempt: int) -> float:
        """Turn a message's identity into a fixed number from 0.0 up to 1.0.

        The same inputs always give the same number. Python's built-in hash()
        changes between runs, so a cryptographic hash is used instead. The
        fault's value ("lost") is used, not the enum itself, because how enums
        turn into text differs between Python versions.
        """
        key = f"{self.seed}|{topic}|{identity}|{fault.value}|{attempt}".encode()
        digest = hashlib.blake2b(key, digest_size=8).digest()
        return int.from_bytes(digest, "big") / 2**64
