"""Home battery: a two-way, limited energy store."""

from __future__ import annotations

from vppsim.errors import fail_validation_if
from vppsim.field.der import DistributedEnergyResource


class Battery(DistributedEnergyResource):
    """A home battery that charges and discharges at the power level it is given.

    It never goes past its power limit, never discharges below its reserve
    (min_soc_kwh, energy kept back e.g. for power cuts) and never charges above
    full. Some energy is lost as heat: delivering E kWh to the
    grid uses E / discharge_efficiency from storage, and drawing E kWh from
    the grid adds only E * charge_efficiency to storage. Energy is in kWh.

    Raises ValidationError if a value is impossible, e.g. a negative size.
    """

    def __init__(
        self,
        device_id: str,
        capacity_kwh: float,
        max_power_kw: float,
        soc_kwh: float,
        charge_efficiency: float = 0.95,
        discharge_efficiency: float = 0.95,
        min_soc_kwh: float = 0.0,
    ) -> None:
        super().__init__(device_id)
        fail_validation_if(capacity_kwh <= 0, "capacity_kwh must be positive")
        fail_validation_if(max_power_kw <= 0, "max_power_kw must be positive")
        fail_validation_if(
            not 0 <= soc_kwh <= capacity_kwh, "soc_kwh must be between 0 and capacity_kwh"
        )
        fail_validation_if(
            not (0 < charge_efficiency <= 1 and 0 < discharge_efficiency <= 1),
            "efficiencies must be in (0, 1]",
        )
        fail_validation_if(
            not 0 <= min_soc_kwh < capacity_kwh, "min_soc_kwh must be at least 0 and below capacity"
        )
        self.capacity_kwh = capacity_kwh
        self.max_power_kw = max_power_kw
        self.soc_kwh = soc_kwh
        self.charge_efficiency = charge_efficiency
        self.discharge_efficiency = discharge_efficiency
        self.min_soc_kwh = min_soc_kwh

    def available_power(self, *, minutes: float) -> tuple[float, float]:
        """Return how fast the battery can charge and discharge for the given minutes.

        Each direction is limited by the power limit and by how much energy can
        be used above the reserve (to discharge) or how much room is left (to
        charge).
        """
        hours = minutes / 60
        usable_kwh = max(self.soc_kwh - self.min_soc_kwh, 0.0)
        max_discharge = min(self.max_power_kw, usable_kwh * self.discharge_efficiency / hours)
        headroom_kwh = self.capacity_kwh - self.soc_kwh
        max_charge = min(self.max_power_kw, headroom_kwh / (self.charge_efficiency * hours))
        return max_charge, max_discharge

    def run_for(self, *, minutes: float) -> float:
        """Charge or discharge for the given minutes and update the stored energy.

        Follows the setpoint but never goes past the limits. Returns the power
        actually delivered, in kW.
        """
        hours = minutes / 60
        floor_kwh = min(self.min_soc_kwh, self.soc_kwh)  # never discharge below this
        max_charge, max_discharge = self.available_power(minutes=minutes)
        if self.setpoint_kw >= 0:
            delivered = min(self.setpoint_kw, max_discharge)
            self.soc_kwh -= delivered * hours / self.discharge_efficiency
        else:
            delivered = -min(-self.setpoint_kw, max_charge)
            self.soc_kwh += -delivered * hours * self.charge_efficiency
        # Guard against floating-point drift past the reserve or capacity.
        self.soc_kwh = min(max(self.soc_kwh, floor_kwh), self.capacity_kwh)
        self.delivered_kw = delivered
        return delivered

    def state_of_charge_kwh(self) -> float | None:
        """Return how much energy is stored, in kWh."""
        return self.soc_kwh
