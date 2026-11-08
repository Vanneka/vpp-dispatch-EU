"""The commercial VPP on a perfect network (the baseline) must give zero tracking error."""

import pytest

from vppsim import InMemoryBroker
from vppsim.experiments.commercial_vpp import default_price_file, run
from vppsim.market import load_prices
from vppsim.vpp import DAY_STEPS, InMemoryStateStore


@pytest.fixture(scope="module")
def results():
    prices = load_prices(default_price_file())[:DAY_STEPS]
    return run(prices, InMemoryBroker(), InMemoryStateStore(), n_batteries=12)


def test_one_result_per_step(results):
    assert [r.step for r in results] == list(range(DAY_STEPS))


def test_perfect_network_delivers_exactly_what_was_allocated(results):
    assert all(r.allocated_kw == pytest.approx(r.delivered_kw, abs=1e-9) for r in results)


def test_batteries_both_charge_and_discharge(results):
    assert any(r.delivered_kw < 0 for r in results)
    assert any(r.delivered_kw > 0 for r in results)


def test_never_allocates_more_than_planned(results):
    assert all(abs(r.allocated_kw) <= abs(r.planned_kw) + 1e-9 for r in results)
