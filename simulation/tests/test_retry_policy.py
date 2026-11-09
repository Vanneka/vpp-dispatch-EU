"""The retry policy: when a command is sent, and when the VPP stops trying."""

import pytest

from vppsim import ValidationError
from vppsim.vpp import RetryPolicy


def test_default_times_double_until_the_end_of_the_step():
    assert RetryPolicy().try_times_s() == [0, 15, 45, 105, 225, 465]


def test_a_shorter_first_wait_gives_more_tries():
    assert RetryPolicy(first_wait_s=4).try_times_s() == [0, 4, 12, 28, 60, 124, 252, 508]


def test_factor_one_retries_at_a_fixed_interval():
    assert RetryPolicy(first_wait_s=300, factor=1).try_times_s() == [0, 300, 600]


def test_a_try_exactly_at_the_deadline_is_left_out():
    assert RetryPolicy(first_wait_s=450, factor=1, deadline_s=900).try_times_s() == [0, 450]


@pytest.mark.parametrize("settings", [{"first_wait_s": 0}, {"factor": 0.5}, {"deadline_s": 0}])
def test_rejects_settings_that_never_send_or_never_stop(settings):
    with pytest.raises(ValidationError):
        RetryPolicy(**settings)
