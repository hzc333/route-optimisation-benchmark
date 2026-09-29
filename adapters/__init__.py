"""Solver adapter registry. Modules are imported lazily so a missing solver
package only breaks the adapters that need it."""

from importlib import import_module

from .base import UnsupportedFeature

_MODULES = {
    "ortools": "adapters.ortools_adapter",
    "pyvrp": "adapters.pyvrp_adapter",
    "vroom": "adapters.vroom_adapter",
}

ADAPTERS = tuple(_MODULES)


def get_adapter(name: str):
    """Return the adapter module; it exposes NAME, VERSION, UNSUPPORTED and solve()."""
    try:
        return import_module(_MODULES[name])
    except KeyError:
        raise ValueError(f"unknown solver {name!r}; choose from {ADAPTERS}") from None


__all__ = ["ADAPTERS", "UnsupportedFeature", "get_adapter"]
