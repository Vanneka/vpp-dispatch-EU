"""A commercial VPP: trade a battery fleet on day-ahead prices (buy cheap, sell expensive).

The run takes any broker, so the same code tests a perfect network (the
baseline) and a faulty one. main() runs the baseline: one day, a perfect
network and the naive dispatcher.

Each step runs four phases, always in this order:
1. the VPP plans, splits the fleet target and sends commands;
2. the broker delivers the commands; control units apply them and reply;
3. every battery runs for 15 minutes; control units send a report;
4. the broker delivers the replies and reports to the VPP.

With a perfect network, every battery should deliver exactly what the VPP
asked for, so the tracking error must be zero. Run it with:

    python -m vppsim.experiments.commercial_vpp [path/to/smard.csv]
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path

from vppsim.field.battery import Battery
from vppsim.field.control_unit import ControlUnit
from vppsim.market.prices import PricePoint, load_prices
from vppsim.network.in_memory_broker import InMemoryBroker
from vppsim.network.message_broker import MessageBroker, ack_topic, command_topic, telemetry_topic
from vppsim.vpp.dispatch_naive import NaiveDispatcher
from vppsim.vpp.planner import DAY_STEPS, plan
from vppsim.vpp.state_store import DeviceSpec, InMemoryStateStore, StateStore

STEP_MINUTES = 15
BATTERY_TYPES = [(5.0, 3.0), (10.0, 5.0), (13.5, 5.0)]  # (capacity kWh, max power kW)
DATA_DIR = Path(__file__).resolve().parents[3] / "data"


@dataclass(frozen=True)
class StepResult:
    """The three fleet totals for one step, in kW."""

    step: int
    price_eur_per_mwh: float
    planned_kw: float  # what the planner wanted
    allocated_kw: float  # what the VPP asked the batteries for, after their limits
    delivered_kw: float  # what the batteries actually did


def build_fleet(n: int) -> list[Battery]:
    """Create n batteries of three types (capacity and power), each half full with a 10% reserve."""
    batteries = []
    for i in range(n):
        capacity, power = BATTERY_TYPES[i % len(BATTERY_TYPES)]
        batteries.append(
            Battery(
                f"b{i:03d}",
                capacity_kwh=capacity,
                max_power_kw=power,
                soc_kwh=capacity * 0.5,
                min_soc_kwh=capacity * 0.1,
            )
        )
    return batteries


def spec_of(battery: Battery) -> DeviceSpec:
    """Return the fixed specs (size, power, reserve, efficiency) the VPP gets at enrollment."""
    return DeviceSpec(
        device_id=battery.device_id,
        capacity_kwh=battery.capacity_kwh,
        max_power_kw=battery.max_power_kw,
        min_soc_kwh=battery.min_soc_kwh,
        charge_efficiency=battery.charge_efficiency,
        discharge_efficiency=battery.discharge_efficiency,
    )


def connect(broker: MessageBroker, control_unit: ControlUnit) -> None:
    """Connect a control unit to the broker: commands in, replies out."""

    def on_command(envelope) -> None:
        ack = control_unit.handle_command(envelope.payload)
        broker.publish(ack_topic(control_unit.device_id), ack, envelope.sent_step)

    broker.subscribe(command_topic(control_unit.device_id), on_command)


def report_all(broker: MessageBroker, control_units: list[ControlUnit], step: int) -> None:
    """Have every control unit send a report of its battery's state."""
    for control_unit in control_units:
        broker.publish(telemetry_topic(control_unit.device_id), control_unit.telemetry(), step)


def run(
    prices: list[PricePoint],
    broker: MessageBroker,
    store: StateStore,
    n_batteries: int = 100,
) -> list[StepResult]:
    """Run the simulation over the given prices and return the totals for each step."""
    batteries = build_fleet(n_batteries)
    control_units = [ControlUnit(b) for b in batteries]
    for battery in batteries:
        store.enroll(spec_of(battery))
    dispatcher = NaiveDispatcher(broker, store, minutes=STEP_MINUTES)
    for control_unit in control_units:
        connect(broker, control_unit)
    targets = plan(prices, fleet_power_kw=sum(b.max_power_kw for b in batteries))

    first_step = prices[0].step
    # Each device announces itself before the first step.
    report_all(broker, control_units, first_step)
    broker.deliver(first_step)

    results = []
    for point, target_kw in zip(prices, targets):
        setpoints = dispatcher.dispatch(target_kw, point.step)  # 1
        broker.deliver(point.step)  # 2
        delivered = sum(b.run_for(minutes=STEP_MINUTES) for b in batteries)  # 3
        report_all(broker, control_units, point.step)
        broker.deliver(point.step)  # 4
        results.append(
            StepResult(point.step, point.eur_per_mwh, target_kw, sum(setpoints.values()), delivered)
        )
    return results


def rmse(values: list[float]) -> float:
    """Return the root mean square of the values: a typical size of the gaps."""
    return math.sqrt(sum(v * v for v in values) / len(values)) if values else 0.0


def print_report(results: list[StepResult]) -> None:
    """Print the active steps and a summary of planned, allocated and delivered energy."""
    print(f"{'step':>4} {'€/MWh':>8} {'planned kW':>11} {'allocated kW':>13} {'delivered kW':>13}")
    for r in results:
        if r.planned_kw or r.allocated_kw or r.delivered_kw:
            print(
                f"{r.step:>4} {r.price_eur_per_mwh:>8.2f} {r.planned_kw:>11.1f}"
                f" {r.allocated_kw:>13.1f} {r.delivered_kw:>13.1f}"
            )
    hours = STEP_MINUTES / 60
    print()
    for name, values in [
        ("planned", [r.planned_kw for r in results]),
        ("allocated", [r.allocated_kw for r in results]),
        ("delivered", [r.delivered_kw for r in results]),
    ]:
        charged = -sum(v for v in values if v < 0) * hours
        discharged = sum(v for v in values if v > 0) * hours
        print(f"{name:>10}: charged {charged:7.1f} kWh, discharged {discharged:7.1f} kWh")
    physics = rmse([r.planned_kw - r.allocated_kw for r in results])
    tracking = rmse([r.allocated_kw - r.delivered_kw for r in results])
    print(f"\nplan the batteries could not meet (RMSE): {physics:.2f} kW")
    print(f"tracking error, allocated vs delivered (RMSE): {tracking:.4f} kW")


def default_price_file() -> Path:
    """Return the SMARD price file in the repository's data folder."""
    files = sorted(DATA_DIR.glob("Day-ahead_prices_*Quarterhour.csv"))
    if not files:
        raise FileNotFoundError(f"no SMARD price file in {DATA_DIR}")
    return files[0]


def main() -> None:
    """Run the baseline for the first day of prices and print the report."""
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else default_price_file()
    prices = load_prices(path)[:DAY_STEPS]
    broker = InMemoryBroker()
    print_report(run(prices, broker, InMemoryStateStore()))
    print(f"messages published: {broker.stats.published}")


if __name__ == "__main__":
    main()
