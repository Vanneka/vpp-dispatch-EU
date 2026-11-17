"""A commercial VPP: trade a battery fleet on day-ahead prices (buy cheap, sell expensive).

The run takes any broker and any dispatcher, so the same code compares the
naive and reliable dispatchers on a perfect network (the baseline) and on a
lossy one. With the same seed, both dispatchers face the same faults.

Each step runs four phases, always in this order:
1. the VPP plans, splits the fleet target and sends commands;
2. delivery rounds, one per send time of the dispatcher (0, 15, 45, ... s):
   the broker delivers the commands, control units apply them and reply,
   the broker delivers the replies, and the VPP re-sends what is unconfirmed;
3. every battery runs for 15 minutes; control units send a report;
4. the broker delivers the reports to the VPP.

Batteries run per step, so a command confirmed at 105 s counts as followed
for the whole step; the seconds show up only in the time to confirm.
Run it with:

    python -m vppsim.experiments.commercial_vpp [path/to/smard.csv]
"""

from __future__ import annotations

import math
import statistics
import sys
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from vppsim.field.battery import Battery
from vppsim.field.control_unit import ControlUnit
from vppsim.market.prices import PricePoint, load_prices
from vppsim.network.faulty_broker import FaultConfig, FaultyBroker
from vppsim.network.in_memory_broker import InMemoryBroker
from vppsim.network.message_broker import MessageBroker, ack_topic, command_topic, telemetry_topic
from vppsim.vpp.dispatch_naive import NaiveDispatcher
from vppsim.vpp.dispatch_reliable import ReliableDispatcher
from vppsim.vpp.dispatcher import Dispatcher
from vppsim.vpp.planner import DAY_STEPS, plan
from vppsim.vpp.state_store import DeviceSpec, InMemoryStateStore, StateStore

STEP_MINUTES = 15
BATTERY_TYPES = [(5.0, 3.0), (10.0, 5.0), (13.5, 5.0)]  # (capacity kWh, max power kW)
DATA_DIR = Path(__file__).resolve().parents[3] / "data"
SEEDS = range(1, 11)  # each seed is a different, repeatable pattern of lost messages

# Each scenario builds a broker from a seed. Both dispatchers get the same seed,
# so they face the same faults.
SCENARIOS: dict[str, Callable[[int], MessageBroker]] = {
    "perfect_network": lambda seed: InMemoryBroker(),
    "lossy_network": lambda seed: FaultyBroker(
        seed, down=FaultConfig(loss=0.1), up=FaultConfig(loss=0.1)
    ),
}
NO_FAULTS = {"perfect_network"}  # nothing is lost here, so one seed is enough
DISPATCHERS: dict[str, Callable[[MessageBroker, StateStore], Dispatcher]] = {
    "naive": lambda broker, store: NaiveDispatcher(broker, store, minutes=STEP_MINUTES),
    "reliable": lambda broker, store: ReliableDispatcher(broker, store, minutes=STEP_MINUTES),
}


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
    dispatcher: Dispatcher,
    n_batteries: int = 100,
) -> list[StepResult]:
    """Run the simulation over the given prices and return the totals for each step.

    The dispatcher must use the same broker and store.
    """
    batteries = build_fleet(n_batteries)
    control_units = [ControlUnit(b) for b in batteries]
    for battery in batteries:
        store.enroll(spec_of(battery))
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
        for time_s in dispatcher.try_times_s():  # 2
            if time_s > 0 and dispatcher.resend(point.step, time_s) == 0:
                break  # everything is confirmed
            broker.deliver(point.step)  # commands reach the control units, which reply
            broker.deliver(point.step)  # replies reach the VPP
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


@dataclass(frozen=True)
class RunSummary:
    """The numbers that compare one dispatcher on one network."""

    scenario: str
    dispatcher: str
    seed: int
    tracking_kw: float  # RMSE of allocated minus delivered
    physics_kw: float  # RMSE of planned minus allocated
    published: int  # messages of every kind
    commands: int
    sends: int
    confirmed: int
    unnecessary_retries: int
    median_confirm_s: float
    p95_confirm_s: float


def summarize(
    scenario: str,
    name: str,
    seed: int,
    results: list[StepResult],
    dispatcher: Dispatcher,
    broker: InMemoryBroker,
) -> RunSummary:
    """Return the comparison numbers for one finished run."""
    stats = dispatcher.stats
    times = sorted(stats.confirm_times_s) or [0.0]
    return RunSummary(
        scenario=scenario,
        dispatcher=name,
        seed=seed,
        tracking_kw=rmse([r.allocated_kw - r.delivered_kw for r in results]),
        physics_kw=rmse([r.planned_kw - r.allocated_kw for r in results]),
        published=broker.stats.published,
        commands=stats.commands,
        sends=stats.sends,
        confirmed=stats.confirmed,
        unnecessary_retries=stats.unnecessary_retries,
        median_confirm_s=statistics.median(times),
        p95_confirm_s=times[math.ceil(0.95 * len(times)) - 1],
    )


def run_one(job: tuple[str, str, int, list[PricePoint], int]) -> RunSummary:
    """Run one scenario with one dispatcher and one seed, and summarize it.

    Takes everything in one tuple so that it can be handed to another process.
    """
    scenario, name, seed, prices, n_batteries = job
    broker, store = SCENARIOS[scenario](seed), InMemoryStateStore()
    dispatcher = DISPATCHERS[name](broker, store)
    results = run(prices, broker, store, dispatcher, n_batteries)
    return summarize(scenario, name, seed, results, dispatcher, broker)


def compare(
    prices: list[PricePoint],
    seeds: Sequence[int],
    n_batteries: int = 100,
    workers: int | None = None,
) -> list[RunSummary]:
    """Run every scenario with every dispatcher once per seed; return one summary per run.

    A network without faults is run with the first seed only, since the
    seed would change nothing there. The runs do not depend on each other,
    so they run side by side on all processor cores (`workers=None`), or one
    after another with `workers=1`. The results are the same either way.
    """
    jobs = [
        (scenario, name, seed, prices, n_batteries)
        for scenario in SCENARIOS
        for seed in (seeds[:1] if scenario in NO_FAULTS else seeds)
        for name in DISPATCHERS
    ]
    if workers == 1:
        return [run_one(job) for job in jobs]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(run_one, jobs))  # map keeps the jobs' order


def spread(values: list[float], fmt: str) -> str:
    """Return the average of the values with their range, e.g. "2.90 (2.61-3.20)"."""
    mean = statistics.fmean(values)
    if min(values) == max(values):
        return format(mean, fmt)
    return f"{mean:{fmt}} ({min(values):{fmt}}-{max(values):{fmt}})"


def print_comparison(rows: list[RunSummary]) -> None:
    """Print one line per scenario and dispatcher: the average over its seeds, with the range."""
    groups: dict[tuple[str, str], list[RunSummary]] = {}
    for r in rows:
        groups.setdefault((r.scenario, r.dispatcher), []).append(r)
    print(
        f"{'scenario':<16} {'dispatcher':<10} {'runs':>4} {'tracking kW':>20}"
        f" {'confirmed':>9} {'sends/cmd':>9} {'p95 s':>6} {'unneeded':>18}"
    )
    for (scenario, dispatcher), runs in groups.items():
        confirmed = [r.confirmed / r.commands if r.commands else 1.0 for r in runs]
        sends = [r.sends / r.commands if r.commands else 0.0 for r in runs]
        print(
            f"{scenario:<16} {dispatcher:<10} {len(runs):>4}"
            f" {spread([r.tracking_kw for r in runs], '.2f'):>20}"
            f" {statistics.fmean(confirmed):>9.1%} {statistics.fmean(sends):>9.2f}"
            f" {statistics.fmean([r.p95_confirm_s for r in runs]):>6.0f}"
            f" {spread([r.unnecessary_retries for r in runs], '.0f'):>18}"
        )
    print(f"\nplan the batteries could not meet (RMSE): {rows[0].physics_kw:.2f} kW")


def default_price_file() -> Path:
    """Return the SMARD price file in the repository's data folder."""
    files = sorted(DATA_DIR.glob("Day-ahead_prices_*Quarterhour.csv"))
    if not files:
        raise FileNotFoundError(f"no SMARD price file in {DATA_DIR}")
    return files[0]


def main() -> None:
    """Run every scenario with every dispatcher over all days of prices and every seed."""
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else default_price_file()
    prices = load_prices(path)
    print(f"{len(prices) / DAY_STEPS:.1f} days of prices, {len(SEEDS)} seeds\n")
    print_comparison(compare(prices, SEEDS))


if __name__ == "__main__":
    main()
