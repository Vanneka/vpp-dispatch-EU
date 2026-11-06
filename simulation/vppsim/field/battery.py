"""Home battery: a two-way, limited energy store."""

from __future__ import annotations

from vppsim.errors import fail_validation_if
from vppsim.field.der import DistributedEnergyResource


class Battery(DistributedEnergyResource):
    """A home battery that charges and discharges at the power level it is given.

    It never goes past its power limit, never discharges below empty and never
    charges above full. Some energy is lost as heat: delivering E kWh to the
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
        self.capacity_kwh = capacity_kwh
        self.max_power_kw = max_power_kw
        self.soc_kwh = soc_kwh
        self.charge_efficiency = charge_efficiency
        self.discharge_efficiency = discharge_efficiency

    def available_power(self, dt_minutes: float) -> tuple[float, float]:
        """Return how fast the battery can charge and discharge for the next interval.

        Each direction is limited by the power limit and by how much energy is
        stored (to discharge) or how much room is left (to charge).
        """
        hours = dt_minutes / 60
        max_discharge = min(self.max_power_kw, self.soc_kwh * self.discharge_efficiency / hours)
        headroom_kwh = self.capacity_kwh - self.soc_kwh
        max_charge = min(self.max_power_kw, headroom_kwh / (self.charge_efficiency * hours))
        return max_charge, max_discharge

    def step(self, dt_minutes: float) -> float:
        """Charge or discharge for one interval and update the stored energy.

        Follows the setpoint but never goes past the limits. Returns the power
        actually delivered, in kW.
        """
        hours = dt_minutes / 60
        max_charge, max_discharge = self.available_power(dt_minutes)
        if self.setpoint_kw >= 0:
            delivered = min(self.setpoint_kw, max_discharge)
            self.soc_kwh -= delivered * hours / self.discharge_efficiency
        else:
            delivered = -min(-self.setpoint_kw, max_charge)
            self.soc_kwh += -delivered * hours * self.charge_efficiency
        # Guard against floating-point drift past the physical bounds.
        self.soc_kwh = min(max(self.soc_kwh, 0.0), self.capacity_kwh)
        self.delivered_kw = delivered
        return delivered

    def state_of_charge_kwh(self) -> float | None:
        """Return how much energy is stored, in kWh."""
        return self.soc_kwh
