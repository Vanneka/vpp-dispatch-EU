"""Project exceptions and guard helpers.

All project errors derive from OperationError, so callers can catch every
simulation error with one except clause. Each specific error also derives
from the matching built-in (e.g. ValueError), so generic handlers still work.
"""

from __future__ import annotations


class OperationError(Exception):
    """Base class for all errors raised by vppsim."""


class ValidationError(OperationError, ValueError):
    """Invalid input or configuration, e.g. a negative capacity."""


class RoutingError(OperationError, ValueError):
    """A message was delivered to the wrong component, e.g. another device's command."""


def fail_validation_if(
    condition: bool,
    message: str,
    error: type[OperationError] = ValidationError,
) -> None:
    """Stop with an error if the condition is true; do nothing otherwise.

    Raises ValidationError by default. Pass another OperationError type as
    `error` for other kinds of failure.
    """
    if condition:
        raise error(message)
