"""Distributed energy resources (DERs): device physics only.

A DER is any small grid-connected energy device, such as a home battery,
rooftop solar or a heat pump. This class models the device itself, whether
or not it is enrolled in a VPP. VPP participation (receiving commands,
reporting telemetry) is handled by a ControlUnit that wraps the device.

Sign convention: positive power = discharging / delivering to the grid,
negative power = charging / drawing from the grid.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from vppsim.errors import fail_validation_if


class DistributedEnergyResource(ABC):
    """A grid-connected energy device that tries to run at the power level it is given.

    That power level is its setpoint, in kW: positive to discharge, negative to
    charge, zero to stay idle. The device gets as close to it as its limits allow.
    A new device starts idle.
    """

    def __init__(self, device_id: str) -> None:
        fail_validation_if(not device_id, "device_id must not be empty")
        self.device_id = device_id
        self.setpoint_kw = 0.0  # the operating point the device tries to follow
        self.delivered_kw = 0.0  # what it actually delivered in the last step

    @abstractmethod
    def available_power(self, dt_minutes: float) -> tuple[float, float]:
        """Return how fast the device can charge and discharge right now.

        Returns (max charge kW, max discharge kW) that it can keep up for the
        whole interval. Both numbers are zero or positive.
        """

    @abstractmethod
    def step(self, dt_minutes: float) -> float:
        """Run the device for one interval at its setpoint, as far as its limits allow.

        Returns the power it actually delivered, in kW.
        """

    def state_of_charge_kwh(self) -> float | None:
        """Return how much energy is stored, in kWh.

        Devices that cannot store energy return None.
        """
        return None
