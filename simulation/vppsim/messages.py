"""Messages exchanged between the VPP and the control units at each site.

Messages are frozen: a sent message never changes in transit, which keeps
duplicate and delayed deliveries identical to the original.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from vppsim.errors import fail_validation_if


@dataclass(frozen=True)
class Command:
    """A dispatch command from the VPP to one device.

    Rule the VPP must follow: a changed instruction always gets a new, higher
    version; a retry re-sends exactly the same command (same ID and version).
    """

    command_id: str
    device_id: str
    version: int  # starts at 1 and increases per device; a higher version replaces lower ones
    setpoint_kw: float

    def __post_init__(self) -> None:
        """Reject commands without an ID or with a version below 1."""
        fail_validation_if(not self.command_id, "command_id must not be empty")
        fail_validation_if(self.version < 1, "version must be at least 1")


class AckReason(str, Enum):
    """What a control unit did with a command."""

    APPLIED = "applied"  # newer version: the device now follows it
    DUPLICATE = "duplicate"  # repeat of the command just applied: nothing changes
    STALE = "stale"  # older than the command just applied: ignored
    CONFLICT = "conflict"  # same version, different ID: a VPP bug, ignored


@dataclass(frozen=True)
class Ack:
    """A control unit's answer to a command."""

    command_id: str
    device_id: str
    version: int
    reason: AckReason

    @property
    def accepted(self) -> bool:
        """Return whether the device is following this command (applied now or before)."""
        return self.reason in (AckReason.APPLIED, AckReason.DUPLICATE)


@dataclass(frozen=True)
class DeviceTelemetry:
    """A control unit's report of its device's current state."""

    device_id: str
    applied_version: int
    setpoint_kw: float
    delivered_kw: float
    soc_kwh: float | None = None  # None for devices without storage
