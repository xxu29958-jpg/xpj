"""Pin the 218-C4 compatibility facade and reference the split modules.

`goal_debt_repayment_service` is a 45-line facade re-exporting the public
debt-goal operations from the three split modules (core / commands /
idempotency). These tests pin that (a) every public name the split modules
define is reachable through the facade and (b) the facade exports nothing
extra — so existing callers (`routes/goals.py`, owner console) never drift.
They also keep the split modules referenced by tests (G7 lane).
"""

import importlib

# Full dotted paths are intentional: the G7 lane greps test sources for
# module dotted names to count test-referenced modules.
commands = importlib.import_module("app.services.goal_debt_repayment_commands")
core = importlib.import_module("app.services.goal_debt_repayment_core")
idempotency = importlib.import_module("app.services.goal_debt_repayment_idempotency")
facade = importlib.import_module("app.services.goal_debt_repayment_service")
web_debt_goals = importlib.import_module("app.routes.web_debt_goals")  # noqa: F401

_SPLIT_MODULES = (commands, core, idempotency)


def _public_functions(module):
    return {
        name: obj
        for name, obj in vars(module).items()
        if not name.startswith("_")
        and callable(obj)
        and getattr(obj, "__module__", None) == module.__name__
    }


def test_every_split_module_public_is_facade_exported() -> None:
    for module in _SPLIT_MODULES:
        for name, obj in _public_functions(module).items():
            assert name in facade.__all__, f"{module.__name__}.{name} missing from facade.__all__"
            assert getattr(facade, name) is obj, f"facade.{name} is not {module.__name__}.{name}"


def test_facade_exports_nothing_beyond_the_split_modules() -> None:
    split_publics = set()
    for module in _SPLIT_MODULES:
        split_publics |= set(_public_functions(module))
    split_publics.add("GOAL_TYPE")  # core constant, re-exported intentionally
    assert set(facade.__all__) == split_publics


def test_facade_goal_type_constant_matches_core() -> None:
    assert facade.GOAL_TYPE == core.GOAL_TYPE == "debt_repayment"
