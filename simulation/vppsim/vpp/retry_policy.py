"""When the VPP re-sends a command that has not been confirmed."""

from __future__ import annotations

from dataclasses import dataclass

from vppsim.errors import fail_validation_if


@dataclass(frozen=True)
class RetryPolicy:
    """Wait, re-send, and wait twice as long each time, until the deadline.

    The first wait starts at 15 s, the IEC 60870-5-104 default for an
    unanswered frame. It is a setting, so experiments can move it up or down.
    The deadline is the end of the 15-minute step.
    """

    first_wait_s: float = 15.0
    factor: float = 2.0
    deadline_s: float = 900.0

    def __post_init__(self) -> None:
        """Reject settings that would never send or never stop."""
        fail_validation_if(self.first_wait_s <= 0, "first_wait_s must be positive")
        fail_validation_if(self.factor < 1, "factor must be at least 1")
        fail_validation_if(self.deadline_s <= 0, "deadline_s must be positive")

    def try_times_s(self) -> list[float]:
        """Return the seconds into the step at which a command is sent: 0 first, then retries.

        With the defaults: 0, 15, 45, 105, 225 and 465 s. The next (945 s)
        would be past the deadline, so it is left out.
        """
        times, time_s, wait_s = [], 0.0, self.first_wait_s
        while time_s < self.deadline_s:
            times.append(time_s)
            time_s += wait_s
            wait_s *= self.factor
        return times
