"""Provider boundary that prevents vendor-specific types from leaking."""

from typing import Protocol

from flyclub.models import RouteDefinition, SearchOutcome


class FlightProvider(Protocol):
    name: str

    def search(self, route: RouteDefinition, *, max_results: int) -> SearchOutcome:
        """Search one route and return only provider-neutral models."""
        ...
