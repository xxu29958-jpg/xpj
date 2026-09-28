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


@pytest.mark.parametrize('kind', ['debt', 'repayment'])
@pytest.mark.parametrize('outcome', ['conflict', 'accepted_then_read_unavailable'])
def test_void_failure_preserves_the_original_command_for_explicit_recovery(monkeypatch, outcome, kind):
    representative_response(monkeypatch)
    monkeypatch.setattr(repayment, 'repayment_context', actual_repayment_context)
    context, _, actor, _ = queries._load_debt_detail_state(None, None)
    import app.services.debt_service as service
    listing = service.list_debt_activity(None)
    current = {'debt': stub_debt(public_id='debt-one', row_version=7)}
    def activity(*args, **kwargs):
        items = [item.model_copy(update={"repayment": item.repayment.model_copy(update={
            "status":"active" if current['debt'].row_version == 7 else "voided"})})
            if item.repayment is not None else item for item in listing.items]
        return listing.model_copy(update={"items":items})
    monkeypatch.setattr(service, 'list_debt_activity', activity)
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
    action = '/web/debts/debt-one/' + ('void' if kind == 'debt' else 'repayment-voids') + '?activity_page=2'
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
    monkeypatch.setattr(commands, 'void_debt_idempotently' if kind == 'debt' else 'void_repayment_idempotently', fault)
    response = (commands.web_void_debt if kind == 'debt' else commands.web_void_repayment)(request, public_id='debt-one', db=db, _local=None, **original)
    assert len(calls) == 1
    payload = {'expected_row_version': 7, 'reason': original['reason']}
    if kind == 'repayment':
        payload['repayment_public_id'] = original['repayment_public_id']
    assert calls[0] == (original['idempotency_key'], payload)
    assert response.status_code == (409 if outcome == 'conflict' else 503)
    returned = hidden_post_forms(response.body.decode())
    assert action in returned, 'Unknown/old command must remain recoverable when the current debt is terminal'
    retry = returned[action]
    assert retry['idempotency_key'] == original['idempotency_key'], 'Recovery must not silently replace the original command key'
    assert retry['expected_row_version'] == original['expected_row_version'], 'Only explicit review may adopt newer OCC'
    assert original['reason'] in response.body.decode()
    assert ('data-void-rejected="true"' in response.body.decode()) is (outcome == 'conflict')


def _void_setup(monkeypatch, kind):
    import app.routes._web_debt_void as void_forms
    import app.routes.web_common as common
    representative_response(monkeypatch)
    monkeypatch.setattr(repayment, "repayment_context", actual_repayment_context)
    context, _, actor, _ = queries._load_debt_detail_state(None, None)
    debt = stub_debt(public_id='debt-one', row_version=7)
    monkeypatch.setattr(queries, '_load_debt_detail_state', lambda *a, **kw:
        (dict(context, debt=queries._detail_view(debt), can_write=True, debt_open=True,
            expected_row_version=7, action_keys=_debt_action_keys()), debt, actor, []))
    for module in (commands, common):
        monkeypatch.setattr(module, '_require_selected_ledger_write', lambda *_: None)
    monkeypatch.setattr(commands, '_list_ledger_options', lambda *_: [])
    monkeypatch.setattr(commands, '_resolve_selected_ledger_id', lambda *a, **kw: 'my-ledger')
    monkeypatch.setattr(commands, '_actor_account_id', lambda *_: 3)
    monkeypatch.setattr(void_forms, '_base_ctx', lambda *a, **kw: dict(context))
    request = Request({'type':'http', 'headers':[], 'method':'POST', 'scheme':'http',
        'server':('testserver',80), 'path':'/web/debts/debt-one/void', 'query_string':b''})
    db = SimpleNamespace(rollback=lambda: None)
    values = void_forms.void_context(request, db, selected_id='my-ledger', public_id='debt-one',
        kind=kind, expected='7', target='repay-one' if kind == 'repayment-void' else '', can_create=True)['values']
    values['reason'] = '原作废原因'
    action = commands.web_void_repayment if kind == 'repayment-void' else commands.web_void_debt
    return request, db, values, action


@pytest.mark.parametrize('kind', ['debt-void', 'repayment-void'])
def test_void_receipt_remains_accepted_when_independent_detail_read_fails(monkeypatch, kind):
    import html
    import json
    import re
    request, db, values, action = _void_setup(monkeypatch, kind)
    monkeypatch.setattr(commands, 'void_repayment_idempotently' if kind == 'repayment-void' else 'void_debt_idempotently',
        lambda *a, **kw: stub_debt(public_id='debt-one', row_version=8, status='voided'))
    def unreadable(*a, **kw):
        raise AppError('dependency_unavailable', status_code=503)
    monkeypatch.setattr(queries, '_load_debt_detail_state', unreadable)
    response = action(request, public_id='debt-one', db=db, _local=None, **values)
    assert response.status_code == 200
    body = response.body.decode()
    ack = json.loads(html.unescape(re.search(r'data-repayment-ack="([^"]+)"', body).group(1)))
    assert ack['clientRef'] == values['idempotency_key']
    assert ack['resultPublicId'] == 'debt-one'
    assert ack['values'] == {name: value for name, value in values.items() if name != 'idempotency_key'}
    assert '原作废提交已接受' in body


@pytest.mark.parametrize('axis', ['datasetId', 'clientGeneration', 'accountId', 'ledgerId', 'deviceId'])
def test_void_original_binding_change_refuses_write_and_keeps_input(monkeypatch, axis):
    import json

    import app.routes._web_debt_void as void_forms
    request, db, values, action = _void_setup(monkeypatch, 'debt-void')
    scope = {'datasetId': 'dataset', 'clientGeneration': 'generation', 'accountId': 'account', 'ledgerId': 'my-ledger', 'deviceId': 'device'}
    monkeypatch.setattr(repayment._web_debt_write, 'repayment_scope', lambda *a: scope)
    monkeypatch.setattr(void_forms, 'repayment_scope', lambda *a: scope)
    original_scope = dict(scope, **{axis:'original'})
    values['origin_binding'] = json.dumps(original_scope)
    monkeypatch.setattr(commands, 'void_debt_idempotently', lambda *a, **kw: pytest.fail('binding refusal must not write'))
    response = action(request, public_id='debt-one', db=db, _local=None, **values)
    assert response.status_code == 409
    forms = hidden_post_forms(response.body.decode())
    returned = next(form for url, form in forms.items() if url.split('?')[0].endswith('/void'))
    assert returned['origin_binding'] == values['origin_binding']
    assert returned['idempotency_key'] == values['idempotency_key']
    assert values['reason'] in response.body.decode()


@pytest.mark.parametrize('kind', ['debt-void', 'repayment-void'])
def test_legacy_accepted_void_requires_review_without_replacement_writer(monkeypatch, kind):
    request, db, values, action = _void_setup(monkeypatch, kind)
    def accepted_legacy(*a, **kw):
        raise AppError('debt_void_original_requires_review', '原作废已被接受，请核对原记录。', status_code=409)
    monkeypatch.setattr(commands, 'void_repayment_idempotently' if kind == 'repayment-void' else 'void_debt_idempotently', accepted_legacy)
    response = action(request, public_id='debt-one', db=db, _local=None, **values)
    assert response.status_code == 409
    body = response.body.decode()
    assert 'data-repayment-result="accepted-review"' in body
    assert '已核对原记录，结束本地恢复' in body
    assert '核对原记录与往来历史' in body
    assert 'data-repayment-replacement' not in body
    assert values['idempotency_key'] in body


@pytest.mark.parametrize('kind', ['debt-void', 'repayment-void'])
def test_void_write_permission_refusal_never_enters_writer(monkeypatch, kind):
    request, db, values, action = _void_setup(monkeypatch, kind)
    def refused(*args):
        raise AppError('permission_denied', '当前身份没有记录权限。', status_code=403)
    monkeypatch.setattr(commands, '_require_selected_ledger_write', refused)
    monkeypatch.setattr(commands, 'void_repayment_idempotently' if kind == 'repayment-void' else 'void_debt_idempotently',
        lambda *a, **kw: pytest.fail('permission refusal must not write'))
    response = action(request, public_id='debt-one', db=db, _local=None, **values)
    assert response.status_code == 403
    assert values['idempotency_key'] in response.body.decode()
    assert values['reason'] in response.body.decode()


@pytest.mark.parametrize('fault_owner', ['detail', 'activity'])
def test_get_read_failure_mounts_all_original_debt_write_recovery_forms(monkeypatch, fault_owner):
    request, db, _, _ = _void_setup(monkeypatch, 'debt-void')
    context, _, _, _ = queries._load_debt_detail_state(None, None)
    monkeypatch.setattr(repayment, '_base_ctx', lambda *a, **kw: dict(context))
    import app.routes._web_debt_write as writes
    monkeypatch.setattr(writes, '_require_selected_ledger_write', lambda *_: None)
    monkeypatch.setattr(queries, '_list_ledger_options', lambda *_: [])
    monkeypatch.setattr(queries, '_resolve_selected_ledger_id', lambda *a, **kw: 'my-ledger')
    def unreadable(*a, **kw):
        raise AppError('dependency_unavailable', status_code=503)
    monkeypatch.setattr(queries, '_load_debt_detail_state' if fault_owner == 'detail' else 'debt_activity_context', unreadable)
    response = queries.web_debt_detail(request, public_id='debt-one', ledger_id='my-ledger', db=db, _local=None)
    assert response.status_code == 503
    body = response.body.decode()
    assert 'data-repayment-kind="debt-void"' in body, 'GET failure must reopen the actual stored debt void'
    assert 'data-repayment-kind="repayment-void"' in body, 'GET failure must reopen the actual stored repayment void'
    forms = {action.split("?")[0]: fields for action, fields in hidden_post_forms(body).items()}
    original_actions = {'/web/debts/debt-one/repayments', '/web/debts/debt-one/void', '/web/debts/debt-one/repayment-voids'}
    assert set(forms) == original_actions | {'/web/debts/debt-one/kind'}
    for action in original_actions:
        assert forms[action]['idempotency_key'] == ''
        assert forms[action]['expected_row_version'] == ''
        assert forms[action]['debt_public_id'] == 'debt-one'
    kind_form = forms['/web/debts/debt-one/kind']
    assert kind_form['idempotency_key'] == '' and kind_form['expected_row_version'] == ''
    assert kind_form['debt_public_id'] == 'debt-one'
    assert kind_form['origin_binding'] == forms['/web/debts/debt-one/repayments']['origin_binding']
    assert 'data-repayment-kind="debt-kind"' in body
    assert '<select id="debt-kind-select"' in body and 'name="debt_kind"' in body
    assert body.count('data-repayment-container') == 4
    assert body.count('data-repayment-can-create="false"') == 4
    assert body.count('data-repayment-can-recover="true"') == 4


@pytest.mark.parametrize("outcome", ["state_conflict", "debt_void_original_requires_review", "dependency_unavailable"])
@pytest.mark.parametrize("target_visible", [True, False])
def test_repayment_void_response_has_one_owner_for_the_original_command(monkeypatch, outcome, target_visible):
    from html.parser import HTMLParser

    import app.services.debt_service as service

    request, db, values, action = _void_setup(monkeypatch, "repayment-void")
    if not target_visible:
        listing = service.list_debt_activity(None)
        monkeypatch.setattr(service, "list_debt_activity", lambda *a, **kw:
            listing.model_copy(update={"items": [item for item in listing.items if item.repayment is None]}))
    def fault(*a, **kw):
        assert kw["idempotency_key"] == values["idempotency_key"]
        assert kw["payload"].expected_row_version == 7
        raise AppError(outcome, status_code=503 if outcome == "dependency_unavailable" else 409)
    monkeypatch.setattr(commands, "void_repayment_idempotently", fault)
    response = action(request, public_id="debt-one", db=db, _local=None, **values)

    class Forms(HTMLParser):
        def __init__(self):
            super().__init__()
            self.forms = []
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == "form" and attrs.get("data-repayment-kind") == "repayment-void":
                self.forms.append(attrs)
    parsed = Forms()
    parsed.feed(response.body.decode())
    assert len(parsed.forms) == 1, "the original local draft/lease must have one usable response owner"
    owner = parsed.forms[0]
    assert owner["data-repayment-result"] == ("accepted-review" if outcome == "debt_void_original_requires_review" else "blocked" if outcome == "state_conflict" else "submitted")
    assert owner["data-void-rejected"] == ("true" if outcome == "state_conflict" else "false")
    returned = hidden_post_forms(response.body.decode())
    original = next(fields for url, fields in returned.items() if "/repayment-voids" in url)
    for name in values.keys() - {"reason"}:
        assert original[name] == values[name]
    assert values["reason"] in response.body.decode()
