"""The VPP's current picture of each battery it controls.

For every enrolled device the store holds two things: its fixed specs,
known from enrollment, and the latest report it sent. The VPP decides using
this picture, which can be out of date when reports are lost or late.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace

from vppsim.errors import RoutingError, fail_validation_if
from vppsim.messages import DeviceTelemetry


@dataclass(frozen=True)
class DeviceSpec:
    """A battery's fixed specs (size, power, reserve, efficiency), given at enrollment."""

    device_id: str
    capacity_kwh: float
    max_power_kw: float
    min_soc_kwh: float = 0.0
    charge_efficiency: float = 0.95
    discharge_efficiency: float = 0.95


@dataclass(frozen=True)
class DeviceView:
    """What the VPP believes about one device: its spec and its latest report."""

    spec: DeviceSpec
    reported: DeviceTelemetry | None = None  # None until the device first reports
    reported_step: int | None = None  # the step that report was sent in

    @property
    def device_id(self) -> str:
        """The name of the device."""
        return self.spec.device_id


class StateStore(ABC):
    """The interface every state store offers."""

    @abstractmethod
    def enroll(self, spec: DeviceSpec) -> None:
        """Start tracking a device. It has no report until it sends one."""

    @abstractmethod
    def update_reported(self, telemetry: DeviceTelemetry, step: int) -> None:
        """Record a device's report, unless a newer one is already stored."""

    @abstractmethod
    def get(self, device_id: str) -> DeviceView:
        """Return what the VPP believes about one device."""

    @abstractmethod
    def all(self) -> list[DeviceView]:
        """Return what the VPP believes about every device, in enrollment order."""


class InMemoryStateStore(StateStore):
    """A state store kept in memory."""

    def __init__(self) -> None:
        self._views: dict[str, DeviceView] = {}

    def enroll(self, spec: DeviceSpec) -> None:
        """Start tracking a device. Raises ValidationError if it is already enrolled."""
        fail_validation_if(spec.device_id in self._views, f"{spec.device_id} is already enrolled")
        self._views[spec.device_id] = DeviceView(spec)

    def update_reported(self, telemetry: DeviceTelemetry, step: int) -> None:
        """Record a device's report, unless a newer one is already stored.

        Raises RoutingError for a device that is not enrolled.
        """
        view = self._views.get(telemetry.device_id)
        fail_validation_if(
            view is None, f"report from unknown device {telemetry.device_id}", error=RoutingError
        )
        if view.reported_step is not None and step < view.reported_step:
            return  # an older report arriving late must not replace a newer one
        self._views[telemetry.device_id] = replace(view, reported=telemetry, reported_step=step)

    def get(self, device_id: str) -> DeviceView:
        """Return what the VPP believes about one device."""
        return self._views[device_id]

    def all(self) -> list[DeviceView]:
        """Return what the VPP believes about every device, in enrollment order."""
        return list(self._views.values())
