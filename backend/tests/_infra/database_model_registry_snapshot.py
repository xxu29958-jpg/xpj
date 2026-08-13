from __future__ import annotations

import hashlib
import inspect
import json
import types
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta, timezone
from dis import get_instructions
from typing import Any

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable, MetaData

ALLOWED_EXTERNAL_METADATA_CALLABLES = frozenset({("uuid", "uuid4")})
ALLOWED_APPLICATION_METADATA_BUILTINS = frozenset({"str"})


def _routine_key(routine: Any) -> tuple[str | None, str | None]:
    return (
        getattr(routine, "__module__", None),
        getattr(routine, "__qualname__", getattr(routine, "__name__", None)),
    )


def _assert_external_metadata_callable_is_allowed(routine: Any) -> None:
    key = _routine_key(routine)
    if key not in ALLOWED_EXTERNAL_METADATA_CALLABLES:
        raise AssertionError(
            "metadata callable crosses an unapproved external runtime boundary: "
            f"{key[0]}.{key[1]}"
        )


def _code_identity(code: types.CodeType, active: frozenset[int]) -> dict[str, Any]:
    return {
        "bytecode": code.co_code.hex(),
        "constants": [_stable_value(value, active) for value in code.co_consts],
        "names": list(code.co_names),
        "varnames": list(code.co_varnames),
        "freevars": list(code.co_freevars),
        "cellvars": list(code.co_cellvars),
        "argcount": code.co_argcount,
        "posonlyargcount": code.co_posonlyargcount,
        "kwonlyargcount": code.co_kwonlyargcount,
        "flags": code.co_flags,
    }


def _application_global_identity(
    function: Any,
    active: frozenset[int],
) -> dict[str, Any]:
    identity = {}
    loaded_names = {
        instruction.argval
        for instruction in get_instructions(function)
        if instruction.opname == "LOAD_GLOBAL"
    }
    builtins_namespace = function.__builtins__
    for name in sorted(loaded_names):
        if name in function.__globals__:
            value = function.__globals__[name]
            if inspect.ismodule(value):
                raise AssertionError(
                    "application metadata callable must not depend on a module global: "
                    f"{function.__module__}.{function.__qualname__}:{name}"
                )
            identity[name] = _stable_value(value, active)
            continue
        if isinstance(builtins_namespace, Mapping):
            value = builtins_namespace.get(name)
        else:
            value = getattr(builtins_namespace, name, None)
        if name not in ALLOWED_APPLICATION_METADATA_BUILTINS or value is None:
            raise AssertionError(
                "application metadata callable uses an unapproved built-in: "
                f"{function.__module__}.{function.__qualname__}:{name}"
            )
        identity[f"builtins.{name}"] = _stable_value(value, active)
    return identity


def _function_identity(function: Any, active: frozenset[int]) -> dict[str, Any]:
    if inspect.ismethod(function):
        raise AssertionError("metadata callable must not capture a bound receiver")
    if not inspect.isfunction(function):
        raise AssertionError(
            "metadata callable is not a serializable Python function: "
            f"{type(function).__module__}.{type(function).__qualname__}"
        )
    if not (function.__module__ or "").startswith("app."):
        _assert_external_metadata_callable_is_allowed(function)
    import_opcodes = {
        instruction.opname
        for instruction in get_instructions(function)
        if instruction.opname in {"IMPORT_NAME", "IMPORT_FROM"}
    }
    if import_opcodes:
        raise AssertionError(
            "application metadata callable must not perform local imports: "
            f"{function.__module__}.{function.__qualname__}:{sorted(import_opcodes)}"
        )
    marker = id(function)
    if marker in active:
        raise AssertionError("metadata callable contains a recursive closure")
    nested_active = active | {marker}
    closure = []
    for cell in function.__closure__ or ():
        try:
            value = cell.cell_contents
        except ValueError:
            closure.append({"empty_cell": True})
        else:
            closure.append(_stable_value(value, nested_active))
    application_globals = {}
    if (function.__module__ or "").startswith("app."):
        application_globals = _application_global_identity(function, nested_active)
    return {
        "module": function.__module__,
        "qualname": function.__qualname__,
        "code": _code_identity(function.__code__, nested_active),
        "defaults": _stable_value(function.__defaults__, nested_active),
        "kwdefaults": _stable_value(function.__kwdefaults__, nested_active),
        "closure": closure,
        "application_globals": application_globals,
    }


def _stable_value(value: Any, active: frozenset[int] = frozenset()) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            raise AssertionError("metadata contains a non-finite float")
        return value
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if isinstance(value, (date, datetime, time)):
        return {
            "temporal_type": type(value).__qualname__,
            "value": value.isoformat(),
        }
    if isinstance(value, timedelta):
        return {"timedelta_microseconds": value // timedelta(microseconds=1)}
    if isinstance(value, timezone):
        return {"timezone": str(value)}
    if inspect.ismodule(value):
        return {"module": value.__name__}
    if inspect.isclass(value):
        return {"type": f"{value.__module__}.{value.__qualname__}"}
    if inspect.isbuiltin(value):
        _assert_external_metadata_callable_is_allowed(value)
        return {
            "builtin": (
                f"{getattr(value, '__module__', None)}."
                f"{getattr(value, '__qualname__', getattr(value, '__name__', None))}"
            )
        }
    if isinstance(value, types.CodeType):
        return {"code": _code_identity(value, active)}
    if inspect.isroutine(value):
        return {"function": _function_identity(value, active)}
    if isinstance(value, (tuple, list)):
        return [_stable_value(item, active) for item in value]
    if isinstance(value, Mapping):
        return [
            (_stable_value(key, active), _stable_value(item, active))
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        ]
    raise AssertionError(
        "metadata contains an unsupported captured value: "
        f"{type(value).__module__}.{type(value).__qualname__}"
    )


def _default_identity(value: Any) -> Any:
    if value is None:
        return None
    argument = getattr(value, "arg", value)
    if callable(argument):
        return {"callable": _function_identity(argument, frozenset())}
    try:
        return _stable_value(argument)
    except AssertionError:
        return {
            "expression_type": (
                f"{type(argument).__module__}.{type(argument).__qualname__}"
            ),
            "expression": str(argument),
        }


def metadata_digest(metadata: MetaData) -> str:
    dialect = postgresql.dialect()
    snapshot = []
    for table_key, table in sorted(metadata.tables.items()):
        snapshot.append(
            {
                "key": table_key,
                "schema": table.schema,
                "comment": table.comment,
                "info": _stable_value(table.info),
                "dialect_kwargs": _stable_value(dict(table.dialect_kwargs)),
                "create_table": str(CreateTable(table).compile(dialect=dialect)),
                "indexes": sorted(
                    str(CreateIndex(index).compile(dialect=dialect))
                    for index in table.indexes
                ),
                "columns": [
                    {
                        "name": column.name,
                        "comment": column.comment,
                        "doc": column.doc,
                        "info": _stable_value(column.info),
                        "default": _default_identity(column.default),
                        "onupdate": _default_identity(column.onupdate),
                        "server_default": _default_identity(column.server_default),
                        "server_onupdate": _default_identity(column.server_onupdate),
                    }
                    for column in table.columns
                ],
            }
        )
    canonical = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
