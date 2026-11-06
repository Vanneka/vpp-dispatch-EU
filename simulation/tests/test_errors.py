"""Guard helper and exception hierarchy."""

import pytest

from vppsim import OperationError, RoutingError, ValidationError, fail_validation_if


def test_no_error_when_condition_false():
    fail_validation_if(False, "never raised")


def test_raises_validation_error_by_default():
    with pytest.raises(ValidationError, match="bad value"):
        fail_validation_if(True, "bad value")


def test_raises_requested_error_type():
    with pytest.raises(RoutingError):
        fail_validation_if(True, "wrong device", error=RoutingError)


def test_hierarchy_allows_broad_and_builtin_catches():
    assert issubclass(ValidationError, OperationError)
    assert issubclass(ValidationError, ValueError)
    assert issubclass(RoutingError, OperationError)
