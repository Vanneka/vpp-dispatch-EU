"""The message broker interface: how messages travel between the VPP and the field.

It follows the publish/subscribe model of MQTT: senders publish a message to
a topic, and the broker hands it to everyone subscribed to that topic. In the
simulation, time moves in steps, so sending and receiving are separate:
`publish` puts a message in the queue, and `deliver` hands out every message
that is due by the current step.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Union

from vppsim.messages import Ack, Command, DeviceTelemetry

Message = Union[Command, Ack, DeviceTelemetry]


def command_topic(device_id: str) -> str:
    """Return the topic the VPP uses to send commands to one device."""
    return f"vpp/der/{device_id}/cmd"


def ack_topic(device_id: str) -> str:
    """Return the topic one device's control unit uses to answer commands."""
    return f"vpp/der/{device_id}/ack"


def telemetry_topic(device_id: str) -> str:
    """Return the topic one device's control unit uses to report its state."""
    return f"vpp/der/{device_id}/telemetry"


def topic_matches(pattern: str, topic: str) -> bool:
    """Return whether a topic fits a subscription pattern.

    Topics are split at "/". A "+" in the pattern matches exactly one part,
    so "vpp/der/+/ack" matches the ack topic of every device.
    """
    pattern_parts, topic_parts = pattern.split("/"), topic.split("/")
    if len(pattern_parts) != len(topic_parts):
        return False
    return all(p in ("+", t) for p, t in zip(pattern_parts, topic_parts))


@dataclass(frozen=True)
class Envelope:
    """A message on its way, with when it was sent and when it arrives."""

    topic: str
    payload: Message
    sent_step: int
    deliver_step: int
    seq: int  # order of entry into the queue; breaks ties within a step


@dataclass
class BrokerStats:
    """Counts of what happened to messages, used for the overhead metric."""

    published: int = 0  # times a sender called publish
    lost: int = 0  # dropped by a fault
    duplicated: int = 0  # extra copies created by a fault
    delivered: int = 0  # envelopes handed out
    unrouted: int = 0  # delivered envelopes that no subscriber wanted


Handler = Callable[[Envelope], None]


class MessageBroker(ABC):
    """The interface every broker offers: subscribe, publish and deliver."""

    @abstractmethod
    def subscribe(self, pattern: str, handler: Handler) -> None:
        """Ask to receive every message whose topic fits the pattern."""

    @abstractmethod
    def publish(self, topic: str, payload: Message, step: int) -> None:
        """Hand a message to the broker at the given step. Nobody receives it yet."""

    @abstractmethod
    def deliver(self, step: int) -> int:
        """Give every message due by this step to its subscribers. Returns how many."""
