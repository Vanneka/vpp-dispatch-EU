"""The commercial VPP: zero tracking error on a perfect network, and retries help on a lossy one."""

import pytest

from vppsim import FaultConfig, FaultyBroker, InMemoryBroker
from vppsim.experiments.commercial_vpp import default_price_file, rmse, run
from vppsim.market import load_prices
from vppsim.vpp import DAY_STEPS, InMemoryStateStore, NaiveDispatcher, ReliableDispatcher

PRICES = load_prices(default_price_file())[:DAY_STEPS]


def simulate(dispatcher_class, broker):
    store = InMemoryStateStore()
    dispatcher = dispatcher_class(broker, store, minutes=15)
    results = run(PRICES, broker, store, dispatcher, n_batteries=12)
    return results, dispatcher


def tracking(results):
    return rmse([r.allocated_kw - r.delivered_kw for r in results])


@pytest.fixture(scope="module")
def results():
    return simulate(NaiveDispatcher, InMemoryBroker())[0]


def test_one_result_per_step(results):
    assert [r.step for r in results] == list(range(DAY_STEPS))


def test_perfect_network_delivers_exactly_what_was_allocated(results):
    assert all(r.allocated_kw == pytest.approx(r.delivered_kw, abs=1e-9) for r in results)


def test_batteries_both_charge_and_discharge(results):
    assert any(r.delivered_kw < 0 for r in results)
    assert any(r.delivered_kw > 0 for r in results)


def test_never_allocates_more_than_planned(results):
    assert all(abs(r.allocated_kw) <= abs(r.planned_kw) + 1e-9 for r in results)


def test_reliable_dispatcher_sends_no_retries_on_a_perfect_network():
    _, dispatcher = simulate(ReliableDispatcher, InMemoryBroker())
    assert dispatcher.stats.sends == dispatcher.stats.commands


def test_lost_commands_cause_tracking_error_only_without_retries():
    lossy = {"down": FaultConfig(loss=0.1)}  # commands lost; replies and reports arrive
    naive, _ = simulate(NaiveDispatcher, FaultyBroker(1, **lossy))
    reliable, _ = simulate(ReliableDispatcher, FaultyBroker(1, **lossy))
    assert tracking(naive) > 0
    assert tracking(reliable) == pytest.approx(0, abs=1e-9)


def test_reliable_dispatcher_confirms_every_command_at_ten_percent_loss():
    faults = {"down": FaultConfig(loss=0.1), "up": FaultConfig(loss=0.1)}
    _, dispatcher = simulate(ReliableDispatcher, FaultyBroker(1, **faults))
    assert dispatcher.stats.confirmed == dispatcher.stats.commands
