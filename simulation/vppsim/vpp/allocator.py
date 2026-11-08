"""Split the fleet target across the batteries."""

from __future__ import annotations

import math
from collections.abc import Iterable

from vppsim.field.battery import available_power_kw
from vppsim.vpp.state_store import DeviceView


def deliverable_kw(view: DeviceView, *, discharging: bool, minutes: float) -> float:
    """Return how much power the VPP believes a battery can give (or take) this step.

    Uses the battery's last report. A battery that has not reported yet gets 0,
    because the VPP cannot count on a battery it knows nothing about.
    """
    if view.reported is None or view.reported.soc_kwh is None:
        return 0.0
    spec = view.spec
    max_charge, max_discharge = available_power_kw(
        soc_kwh=view.reported.soc_kwh,
        capacity_kwh=spec.capacity_kwh,
        min_soc_kwh=spec.min_soc_kwh,
        max_power_kw=spec.max_power_kw,
        charge_efficiency=spec.charge_efficiency,
        discharge_efficiency=spec.discharge_efficiency,
        minutes=minutes,
    )
    return max_discharge if discharging else max_charge


def allocate(
    target_kw: float,
    views: Iterable[DeviceView],
    *,
    minutes: float,
    resolution_kw: float = 0.01,
) -> dict[str, float]:
    """Return a setpoint for each battery so that together they meet the fleet target.

    Each battery gets a share in proportion to what it can deliver, so a
    battery that can give twice as much is asked for twice as much. If the
    target is more than the whole fleet can do, every battery is asked for
    its maximum. Setpoints are rounded towards zero to `resolution_kw`, so a
    battery is never asked for more than it can deliver.
    """
    views = list(views)
    if target_kw == 0:
        return {v.device_id: 0.0 for v in views}
    discharging = target_kw > 0
    capable = {
        v.device_id: deliverable_kw(v, discharging=discharging, minutes=minutes) for v in views
    }
    total = sum(capable.values())
    share = min(abs(target_kw) / total, 1.0) if total > 0 else 0.0
    sign = 1.0 if discharging else -1.0
    return {
        device_id: sign * _round_down(kw * share, resolution_kw)
        for device_id, kw in capable.items()
    }


def _round_down(kw: float, resolution_kw: float) -> float:
    """Round a non-negative power down to the resolution, never above the input.

    Plain float arithmetic can land a hair above the input (3.8000000000000003
    for 3.8), so the result is capped at the input itself.
    """
    rounded = round(math.floor(kw / resolution_kw + 1e-9) * resolution_kw, 9)
    return min(rounded, kw)
