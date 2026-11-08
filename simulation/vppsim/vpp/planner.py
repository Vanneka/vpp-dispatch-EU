"""Turn prices into a fleet target for each step: buy cheap, sell expensive."""

from __future__ import annotations

from collections.abc import Sequence

from vppsim.errors import fail_validation_if
from vppsim.market.prices import PricePoint

DAY_STEPS = 96  # 15-minute steps in a day


def plan(
    prices: Sequence[PricePoint],
    fleet_power_kw: float,
    slots: int = 8,
    block: int = DAY_STEPS,
) -> list[float]:
    """Return a fleet target in kW for each price: negative to charge, positive to discharge.

    The prices are taken in blocks of `block` steps (one day by default). In
    each block, the `slots` cheapest steps charge at full fleet power, the
    `slots` most expensive discharge at full fleet power, and the rest stay
    idle. A shorter final block uses fewer slots so the two never overlap.
    The plan ignores how full the batteries are; the allocator handles that.
    """
    fail_validation_if(fleet_power_kw <= 0, "fleet_power_kw must be positive")
    fail_validation_if(slots < 0, "slots must not be negative")
    fail_validation_if(2 * slots > block, "slots must fit twice into a block")
    targets = [0.0] * len(prices)
    for start in range(0, len(prices), block):
        positions = range(start, min(start + block, len(prices)))
        by_price = sorted(positions, key=lambda i: (prices[i].eur_per_mwh, i))
        n = min(slots, len(by_price) // 2)
        for i in by_price[:n]:
            targets[i] = -fleet_power_kw
        for i in by_price[len(by_price) - n :]:
            targets[i] = fleet_power_kw
    return targets
