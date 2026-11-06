"""A perfect, in-memory broker. Phase 3 replaces it with a real MQTT broker."""

from __future__ import annotations

import heapq

from vppsim.errors import fail_validation_if
from vppsim.network.message_broker import (
    BrokerStats,
    Envelope,
    Handler,
    Message,
    MessageBroker,
    topic_matches,
)


class InMemoryBroker(MessageBroker):
    """A perfect broker: every message arrives once, in the order it was sent.

    Messages published while `deliver` is running wait for the next
    `deliver` call, so each phase of a simulation step stays separate.
    """

    def __init__(self) -> None:
        self.stats = BrokerStats()
        self._subscriptions: list[tuple[str, Handler]] = []
        self._queue: list[tuple[int, int, Envelope]] = []
        self._next_seq = 0

    def subscribe(self, pattern: str, handler: Handler) -> None:
        """Ask to receive every message whose topic fits the pattern."""
        self._subscriptions.append((pattern, handler))

    def publish(self, topic: str, payload: Message, step: int) -> None:
        """Queue a message for delivery in the same step."""
        fail_validation_if(step < 0, "step must not be negative")
        self.stats.published += 1
        self._enqueue(topic, payload, sent_step=step, deliver_step=step)

    def deliver(self, step: int) -> int:
        """Give every message due by this step to its subscribers, earliest due first."""
        due: list[Envelope] = []
        while self._queue and self._queue[0][0] <= step:
            due.append(heapq.heappop(self._queue)[2])
        for envelope in due:
            self._hand_out(envelope)
        return len(due)

    def pending(self) -> int:
        """Return how many messages are still waiting to be delivered."""
        return len(self._queue)

    def _enqueue(self, topic: str, payload: Message, sent_step: int, deliver_step: int) -> None:
        """Put one copy of a message in the queue, sorted by when it is due."""
        envelope = Envelope(topic, payload, sent_step, deliver_step, self._next_seq)
        heapq.heappush(self._queue, (deliver_step, self._next_seq, envelope))
        self._next_seq += 1

    def _hand_out(self, envelope: Envelope) -> None:
        """Call every handler whose subscription fits the envelope's topic."""
        self.stats.delivered += 1
        handlers = [h for p, h in self._subscriptions if topic_matches(p, envelope.topic)]
        if not handlers:
            self.stats.unrouted += 1
        for handler in handlers:
            handler(envelope)
