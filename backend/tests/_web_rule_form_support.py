"""Submit the currency, requested state and key carried by the real rule form."""

from tests._web_native_form_support import hidden_post_forms


def submit_rule_form(client, action, *, data, follow_redirects=True):
    ledger_id = data.get("ledger_id", "owner")
    page = client.get("/web/rules", params={"ledger_id": ledger_id})
    assert page.status_code == 200, page.text
    fields = hidden_post_forms(page.text)[action]
    return client.post(action, data={**fields, **data}, follow_redirects=follow_redirects)
