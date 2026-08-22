"""Deterministic contract checks for PostgreSQL maintenance role observations."""

from types import SimpleNamespace

from app.database._managed_postgres_role_authority import _assert_role_attributes


class _Rows:
    def __init__(self, rows: tuple[tuple[object, ...], ...]) -> None:
        self._rows = rows

    def all(self) -> tuple[tuple[object, ...], ...]:
        return self._rows


class _Connection:
    def execute(self, _statement, _parameters) -> _Rows:
        return _Rows(
            (
                ("a_owner", False, False, False, False, False, False, False),
                ("z_migrator", True, False, False, False, False, False, False),
            )
        )


def test_role_attribute_observation_does_not_require_role_name_order() -> None:
    _assert_role_attributes(
        _Connection(),
        SimpleNamespace(schema_owner_role="a_owner", migrator_role="z_migrator"),
    )
