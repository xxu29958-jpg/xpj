from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def test_parser_reads_every_dispatcher_implementation_in_one_file() -> None:
    mod = importlib.reload(importlib.import_module("_audit_android_outbox_dispatcher_coverage"))
    source = """
class CreateExpenseOffsetDispatcher(
    private val api: ApiService,
) : OutboxMutationDispatcher {
    override val type = PendingMutationType.CreateExpenseOffset
}

class VoidExpenseOffsetDispatcher(
    private val api: ApiService,
) : OutboxMutationDispatcher {
    override val type = PendingMutationType.VoidExpenseOffset
}
"""

    assert mod.parse_dispatchers({"ExpenseOffsetDispatchers.kt": source}) == {
        "CreateExpenseOffset": "CreateExpenseOffsetDispatcher",
        "VoidExpenseOffset": "VoidExpenseOffsetDispatcher",
    }


RULE_DISPATCHER = """
class CategoryRuleDispatcher(
    override val type: PendingMutationType,
    private val apiProvider: (OutboxRow) -> ApiService,
) : OutboxMutationDispatcher {
    override suspend fun dispatch(row: OutboxRow) = consume(row)
}
"""
RULE_TYPES = {"CreateCategoryRule", "UpdateCategoryRule", "DeleteCategoryRule"}


def _registry(*types):
    calls = ",\n".join(f"CategoryRuleDispatcher({value}, ::outboxApi)" for value in types)
    return f"class AppContainer {{ val outboxDispatchers = listOf({calls}) }}"


def test_constructor_type_resolves_each_real_registered_mutation():
    mod = importlib.import_module("_audit_android_outbox_dispatcher_coverage")
    source = _registry(*(f"PendingMutationType.{name}" for name in sorted(RULE_TYPES)))
    result = mod.parse_dispatchers({"Rules.kt": RULE_DISPATCHER}, source)
    assert result == dict.fromkeys(RULE_TYPES, "CategoryRuleDispatcher")


def test_named_constructor_type_and_nested_arguments_are_resolved():
    mod = importlib.import_module("_audit_android_outbox_dispatcher_coverage")
    source = """val outboxDispatchers = listOf(
        CategoryRuleDispatcher(apiProvider = provider(factory(1, 2)), type = PendingMutationType.CreateCategoryRule),
    )"""
    assert mod.parse_dispatchers({"Rules.kt": RULE_DISPATCHER}, source) == {"CreateCategoryRule": "CategoryRuleDispatcher"}


@pytest.mark.parametrize("value", ["Unknown", "NotDeclared"])
def test_constructor_type_rejects_unknown_or_undeclared_constants(value):
    mod = importlib.import_module("_audit_android_outbox_dispatcher_coverage")
    source = _registry(f"PendingMutationType.{value}")
    mapping = mod.parse_dispatchers({"Rules.kt": RULE_DISPATCHER}, source)
    problems = mod.evaluate(enum_types=RULE_TYPES | {"Unknown"}, dispatcher_map=mapping,
        registered_classes=mod.parse_registered_classes(source), enqueue_types={}, allowlist_no_callsite=frozenset())
    assert any(value in problem for problem in problems)


@pytest.mark.parametrize("argument", ["runtimeType", "type = unknownType", ""])
def test_unresolved_constructor_type_cannot_silently_pass(argument):
    mod = importlib.import_module("_audit_android_outbox_dispatcher_coverage")
    with pytest.raises(ValueError, match="constructor type"):
        mod.parse_dispatchers({"Rules.kt": RULE_DISPATCHER}, _registry(argument))


def test_duplicate_constructor_registration_is_rejected():
    mod = importlib.import_module("_audit_android_outbox_dispatcher_coverage")
    source = _registry("PendingMutationType.CreateCategoryRule", "PendingMutationType.CreateCategoryRule")
    with pytest.raises(ValueError, match="duplicate"):
        mod.parse_dispatchers({"Rules.kt": RULE_DISPATCHER}, source)


def test_fixed_dispatcher_duplicates_are_rejected_in_registry_and_implementations():
    mod = importlib.import_module("_audit_android_outbox_dispatcher_coverage")
    fixed = "class FixedDispatcher : OutboxMutationDispatcher { override val type = PendingMutationType.CreateCategoryRule }"
    with pytest.raises(ValueError, match="duplicate dispatcher registration"):
        mod.parse_dispatchers({"Fixed.kt": fixed}, "val outboxDispatchers = listOf(FixedDispatcher(), FixedDispatcher())")
    with pytest.raises(ValueError, match="duplicate dispatcher implementation"):
        mod.parse_dispatchers({"Fixed.kt": fixed, "Other.kt": fixed.replace("FixedDispatcher", "OtherDispatcher")})


def test_positional_type_uses_its_declared_parameter_index():
    mod = importlib.import_module("_audit_android_outbox_dispatcher_coverage")
    source = RULE_DISPATCHER.replace("override val type: PendingMutationType,",
        "private val values: Map<String, Int>, override val type: PendingMutationType,")
    registry = "val outboxDispatchers = listOf(CategoryRuleDispatcher(mapOf(1 to 2), PendingMutationType.CreateCategoryRule, ::api))"
    assert mod.parse_dispatchers({"Rules.kt": source}, registry) == {"CreateCategoryRule": "CategoryRuleDispatcher"}


def test_positional_enqueue_is_a_producer_but_catalogues_and_comments_are_not():
    mod = importlib.import_module("_audit_android_outbox_dispatcher_coverage")
    source = """
        enqueue(bound, PendingMutationType.CreateCategoryRule, payload)
        enqueue(bound, PendingMutationType.UpdateCategoryRule, payload)
        enqueue(bound, PendingMutationType.NotDeclared, payload)
        val types = setOf(PendingMutationType.DeleteCategoryRule)
        val type = PendingMutationType.fromWire(raw)
        // enqueue(bound, PendingMutationType.DeleteCategoryRule, payload)
        val note = "type = PendingMutationType.Unknown"
    """
    assert mod.parse_enqueues({"Rules.kt": source}, RULE_TYPES | {"Unknown"}) == {
        "CreateCategoryRule": {"Rules.kt"}, "UpdateCategoryRule": {"Rules.kt"}, "NotDeclared": {"Rules.kt"},
    }


def test_missing_one_parameterized_registration_still_fails_for_its_actual_producer():
    mod = importlib.import_module("_audit_android_outbox_dispatcher_coverage")
    source = _registry("PendingMutationType.CreateCategoryRule", "PendingMutationType.UpdateCategoryRule")
    mapping = mod.parse_dispatchers({"Rules.kt": RULE_DISPATCHER}, source)
    enqueues = mod.parse_enqueues({"Repository.kt": "enqueue(bound, PendingMutationType.DeleteCategoryRule, payload)"}, RULE_TYPES)
    problems = mod.evaluate(enum_types=RULE_TYPES | {"Unknown"}, dispatcher_map=mapping,
        registered_classes=mod.parse_registered_classes(source), enqueue_types=enqueues, allowlist_no_callsite=frozenset())
    assert any("DeleteCategoryRule is enqueued" in problem and "no dispatcher" in problem for problem in problems)


def test_live_rule_and_income_dispatchers_cover_each_registered_type():
    mod = importlib.import_module("_audit_android_outbox_dispatcher_coverage")
    files, source = mod._kt_files(mod.ANDROID_SRC), mod._read(mod.APP_CONTAINER)
    mapping = mod.parse_dispatchers(files, source)
    enqueues = mod.parse_enqueues(files, mod.parse_enum_types(mod._read(mod.TYPE_FILE)))
    for name in RULE_TYPES:
        assert mapping[name] == "CategoryRuleDispatcher" and enqueues[name]
    for name in ("CreateIncomePlan", "UpdateIncomePlan"):
        assert mapping[name] == "IncomePlanDispatcher" and enqueues[name]
