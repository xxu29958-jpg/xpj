"""Probe current native void recovery; mock the command fault, render real user forms."""
from types import SimpleNamespace

import pytest
from starlette.requests import Request

import app.routes._web_debt_repayment as repayment
import app.routes.web_debt_actions as commands
import app.routes.web_debts as queries
from app.errors import AppError
from app.routes._web_debt_repayment import repayment_context as actual_repayment_context
from app.routes._web_debt_write import _debt_action_keys
from tests._web_debt_test_support import stub_debt
from tests._web_native_form_support import hidden_post_forms
from tests.test_web_debt_activity_view import representative_response


@pytest.mark.parametrize('outcome', ['conflict', 'accepted_then_read_unavailable'])
def test_void_failure_preserves_the_original_command_for_explicit_recovery(monkeypatch, outcome):
    representative_response(monkeypatch)
    monkeypatch.setattr(repayment, 'repayment_context', actual_repayment_context)
    context, _, actor, _ = queries._load_debt_detail_state(None, None)
    current = {'debt': stub_debt(public_id='debt-one', row_version=7)}
    def load(*args, **kwargs):
        debt = current['debt']
        ctx = dict(context, debt=queries._detail_view(debt), can_write=True,
                   debt_open=debt.status == 'open', expected_row_version=debt.row_version,
                   action_keys=_debt_action_keys())
        return ctx, debt, actor, []
    monkeypatch.setattr(queries, '_load_debt_detail_state', load)
    monkeypatch.setattr(commands, '_list_ledger_options', lambda *_: [])
    monkeypatch.setattr(commands, '_resolve_selected_ledger_id', lambda *_a, **_kw: 'my-ledger')
    monkeypatch.setattr(commands, '_require_selected_ledger_write', lambda *_: None)
    monkeypatch.setattr(commands, '_actor_account_id', lambda *_: 3)
    request = Request({'type': 'http', 'method': 'POST', 'scheme': 'http', 'server': ('testserver', 80),
                       'path': '/web/debts/debt-one/void', 'query_string': b'ledger_id=my-ledger', 'headers': []})
    db = SimpleNamespace(rollback=lambda: None)
    first = queries._render_debt_detail(request, db, options=[], selected_id='my-ledger', public_id='debt-one')
    action = '/web/debts/debt-one/void'
    original = hidden_post_forms(first.body.decode())[action]
    assert original['ledger_id'] == 'my-ledger'
    assert original['expected_row_version'] == '7'
    assert original['idempotency_key']
    original['reason'] = 'Repeated entry; keep this original reason'
    calls = []
    def fault(*_args, **kwargs):
        calls.append((kwargs['idempotency_key'], kwargs['payload'].model_dump()))
        current['debt'] = stub_debt(public_id='debt-one', row_version=8,
            status='voided' if outcome == 'accepted_then_read_unavailable' else 'open',
            remaining_amount_cents=0 if outcome == 'accepted_then_read_unavailable' else 50000)
        if outcome == 'conflict':
            raise AppError('state_conflict', status_code=409)
        raise AppError('dependency_unavailable', 'The command result cannot currently be read.', status_code=503)
    monkeypatch.setattr(commands, 'void_debt_idempotently', fault)
    response = commands.web_void_debt(request, public_id='debt-one', db=db, _local=None, **original)
    assert len(calls) == 1
    assert calls[0] == (original['idempotency_key'], {'expected_row_version': 7, 'reason': original['reason']})
    assert response.status_code == (409 if outcome == 'conflict' else 503)
    returned = hidden_post_forms(response.body.decode())
    assert action in returned, 'Unknown/old command must remain recoverable when the current debt is terminal'
    retry = returned[action]
    assert retry['idempotency_key'] == original['idempotency_key'], 'Recovery must not silently replace the original command key'
    assert retry['expected_row_version'] == original['expected_row_version'], 'Only explicit review may adopt newer OCC'
    assert original['reason'] in response.body.decode()
