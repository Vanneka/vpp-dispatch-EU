"""The control unit at a site: what makes a DER part of the VPP.

Real VPPs install a remote control unit at each site (for example Next
Kraftwerke's Next Box, or the control box behind a German smart meter
gateway). The unit receives the VPP's commands, applies them to the device
at most once, and reports the device's state. A DER without a control unit
is simply not enrolled.
"""

from __future__ import annotations

from vppsim.errors import RoutingError, fail_validation_if
from vppsim.field.der import DistributedEnergyResource
from vppsim.messages import Ack, AckReason, Command, DeviceTelemetry


class ControlUnit:
    """Connects one DER to the VPP and makes sure each command is applied only once.

    Every command has a version number, and each new command from the VPP
    has a higher number than the one before. The control unit remembers the
    number and ID of the last command it applied. When a command arrives:
    a higher number is new, so it is applied; a lower number is out of date,
    so it is ignored; the same number and ID is a repeat, so it is not
    applied again.
    """

    def __init__(self, der: DistributedEnergyResource) -> None:
        self.der = der
        self.applied_version = 0
        self.last_applied_command_id: str | None = None

    @property
    def device_id(self) -> str:
        """The name of the device this unit controls."""
        return self.der.device_id

    def handle_command(self, cmd: Command) -> Ack:
        """Receive a command from the VPP and apply it only if it is new.

        The reply's reason says what happened:
        - APPLIED: a newer version, so the device now follows it.
        - DUPLICATE: a repeat of the command just applied; nothing changes.
        - STALE: older than the command just applied; ignored.
        - CONFLICT: same version as the command just applied but a different
          ID, which means the VPP broke the versioning rule; ignored.

        Raises RoutingError if the command is meant for a different device.
        """
        fail_validation_if(
            cmd.device_id != self.device_id,
            f"command for {cmd.device_id} delivered to {self.device_id}",
            error=RoutingError,
        )
        if cmd.version > self.applied_version:
            self.der.setpoint_kw = cmd.setpoint_kw
            self.applied_version = cmd.version
            self.last_applied_command_id = cmd.command_id
            return self._ack(cmd, AckReason.APPLIED)
        if cmd.version == self.applied_version:
            if cmd.command_id == self.last_applied_command_id:
                # Re-send the ack so the VPP can stop retrying.
                return self._ack(cmd, AckReason.DUPLICATE)
            return self._ack(cmd, AckReason.CONFLICT)
        return self._ack(cmd, AckReason.STALE)

    def telemetry(self) -> DeviceTelemetry:
        """Report the device's current state to the VPP."""
        return DeviceTelemetry(
            device_id=self.device_id,
            applied_version=self.applied_version,
            setpoint_kw=self.der.setpoint_kw,
            delivered_kw=self.der.delivered_kw,
            soc_kwh=self.der.state_of_charge_kwh(),
        )

    def _ack(self, cmd: Command, reason: AckReason) -> Ack:
        """Build the reply to a command."""
        return Ack(cmd.command_id, self.device_id, cmd.version, reason)
