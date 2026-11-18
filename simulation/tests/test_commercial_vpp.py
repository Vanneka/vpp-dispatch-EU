"""The commercial VPP: zero tracking error on a perfect network, and retries help on a lossy one."""

import pytest

from vppsim import FaultConfig, FaultyBroker, InMemoryBroker
from vppsim.experiments.commercial_vpp import compare, default_price_file, rmse, run
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


@pytest.fixture(scope="module")
def three_seeds():
    return compare(PRICES, [1, 2, 3], n_batteries=12, workers=1)


def runs(rows, scenario, dispatcher):
    return [r for r in rows if r.scenario == scenario and r.dispatcher == dispatcher]


def test_perfect_network_is_run_with_one_seed_only(three_seeds):
    assert len(runs(three_seeds, "perfect_network", "naive")) == 1
    assert len(runs(three_seeds, "lossy_network", "naive")) == 3


def test_the_same_seed_gives_the_same_result(three_seeds):
    again = compare(PRICES, [1], n_batteries=12)  # side by side this time
    first = runs(three_seeds, "lossy_network", "naive")[0]
    assert runs(again, "lossy_network", "naive")[0] == first


def test_different_seeds_lose_different_messages(three_seeds):
    tracking = [r.tracking_kw for r in runs(three_seeds, "lossy_network", "naive")]
    assert len(set(tracking)) == 3


def test_reliable_beats_naive_for_every_seed(three_seeds):
    naive = runs(three_seeds, "lossy_network", "naive")
    reliable = runs(three_seeds, "lossy_network", "reliable")
    assert all(r.tracking_kw < n.tracking_kw for n, r in zip(naive, reliable))
    assert all(r.confirmed == r.commands for r in reliable)


def test_parallel_and_one_by_one_give_the_same_rows(three_seeds):
    assert compare(PRICES, [1, 2, 3], n_batteries=12, workers=2) == three_seeds


@pytest.mark.parametrize("dispatcher_class", [NaiveDispatcher, ReliableDispatcher])
def test_repeated_messages_alone_cause_no_tracking_error(dispatcher_class):
    repeats = {"down": FaultConfig(duplicate=0.1), "up": FaultConfig(duplicate=0.1)}
    results, dispatcher = simulate(dispatcher_class, FaultyBroker(1, **repeats))
    assert dispatcher.stats.duplicate_replies > 0  # repeated commands did arrive ...
    assert tracking(results) == pytest.approx(0, abs=1e-9)  # ... and were applied only once


def test_reliable_beats_naive_when_messages_are_lost_and_repeated(three_seeds):
    naive = runs(three_seeds, "lossy_duplicating", "naive")
    reliable = runs(three_seeds, "lossy_duplicating", "reliable")
    assert all(r.tracking_kw < n.tracking_kw for n, r in zip(naive, reliable))
    assert all(r.confirmed == r.commands for r in reliable)
