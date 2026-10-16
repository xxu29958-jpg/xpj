"""Credential-write audit must see Kotlin implicit receivers, not declarations."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _audit_source(tmp_path, monkeypatch, source, *, sanctioned=False):
    audit = importlib.import_module("_audit_android_session_binding_contract")
    root = tmp_path / "src"
    target = root / "gray" / "java" / "Session.kt"
    target.parent.mkdir(parents=True)
    target.write_text(source, encoding="utf-8")
    monkeypatch.setattr(audit, "ANDROID_SRC", root)
    allowed = {"gray/java/Session.kt::establishSession": "test transition owner"} if sanctioned else {}
    monkeypatch.setattr(audit, "ALLOWLIST", allowed)
    return audit


@pytest.mark.parametrize(
    "source",
    [
        "fun bypass() { store.establishSession(record) }",
        "val bypass = store::establishSession",
        "suspend fun LocalSessionStore.bypass() { establishSession(record) }",
        "fun bypass() { with(store) { establishSession(record) } }",
    ],
)
def test_unsanctioned_receiver_forms_are_rejected(tmp_path, monkeypatch, capsys, source):
    audit = _audit_source(tmp_path, monkeypatch, source)
    assert audit.main() == 1
    assert "unsanctioned credential write gray/java/Session.kt::establishSession" in capsys.readouterr().out


def test_declarations_and_non_code_do_not_create_writes(tmp_path, monkeypatch):
    audit = _audit_source(
        tmp_path,
        monkeypatch,
        '''
        interface Store { suspend fun establishSession(record: Record) }
        suspend fun LocalSessionStore.establishSession(record: Record) {}
        fun <T> establishSession(record: T) {}
        // establishSession(record)
        val example = "store.establishSession(record)"
        ''',
    )
    assert audit.main() == 0


def test_implicit_transition_write_is_still_sanctioned(tmp_path, monkeypatch):
    audit = _audit_source(
        tmp_path,
        monkeypatch,
        "suspend fun LocalSessionStore.persist() { establishSession(record) }",
        sanctioned=True,
    )
    assert audit.main() == 0


def test_extra_implicit_write_does_not_hide_behind_allowed_explicit_write(tmp_path, monkeypatch, capsys):
    audit = _audit_source(
        tmp_path,
        monkeypatch,
        "fun persist() { store.establishSession(record); with(store) { establishSession(record) } }",
        sanctioned=True,
    )
    assert audit.main() == 1
    assert "occurs 2 times" in capsys.readouterr().out
