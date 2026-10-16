"""Read the hidden fields a native browser would submit from server-rendered forms."""

import re
from copy import deepcopy
from html import unescape
from html.parser import HTMLParser

_TIME_FIELDS = {"time_precision", "calendar_revision", "user_local_date", "source_timezone",
    "source_utc_offset_seconds", "accounting_date", "expense_time", "spent_at", "paid_at", "payment_date"}


class _PostForms(HTMLParser):
    def __init__(self, html: str) -> None:
        super().__init__()
        self.forms: dict[str, dict[str, str]] = {}
        self.current: dict[str, str] | None = None
        self.time_select: str | None = None
        self.disabled_fieldsets: list[bool] = []
        self.feed(html)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "fieldset":
            self.disabled_fieldsets.append("disabled" in values or any(self.disabled_fieldsets))
        if any(self.disabled_fieldsets):
            return
        if tag == "form" and values.get("method", "").lower() == "post":
            self.current = self.forms.setdefault(values.get("action", ""), {})
        if tag == "input":
            self._read_input(values)
        self._read_time_select(tag, values)

    def _read_input(self, values: dict[str, str | None]) -> None:
        if self.current is not None and (
            values.get("type") in {"hidden", "month"} or values.get("name") in _TIME_FIELDS
        ):
            name = values.get("name")
            if name and "disabled" not in values:
                self.current[name] = values.get("value") or ""

    def _read_time_select(self, tag: str, values: dict[str, str | None]) -> None:
        if tag == "select" and values.get("name") in _TIME_FIELDS and "disabled" not in values:
            self.time_select = values["name"]
        if (tag == "option" and self.time_select and self.current is not None
            and (self.time_select not in self.current or "selected" in values)):
            self.current[self.time_select] = values.get("value") or ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "fieldset" and self.disabled_fieldsets:
            self.disabled_fieldsets.pop()
        if tag == "form":
            self.current = None
        if tag == "select":
            self.time_select = None


def hidden_post_forms(html: str) -> dict[str, dict[str, str]]:
    """Hidden identity plus native month and indivisible accounting-time controls."""
    return _PostForms(html).forms


def open_creation_form(client, page, parameter: str, *, headers=None):
    """Follow the rendered task entry, including its selected ledger and period."""
    href = next(unescape(href) for href in re.findall(r'<a[^>]*href="([^"]+)"', page.text)
        if parameter + "=1" in href)
    response = client.get(href, headers=headers)
    assert response.status_code == 200, response.text
    return response


def open_repayment_task(client, page, *, headers=None):
    """Follow the actual debt detail entry with its original ledger and task kind."""
    href = next(unescape(href) for href in re.findall(
        r'<a\b[^>]*href="([^"]+)"[^>]*data-repayment-task-kind=', page.text))
    response = client.get(href, headers=headers)
    assert response.status_code == 200, response.text
    return response


def accounting_time_fields(html: str) -> dict[str, str]:
    return {name: value for form in hidden_post_forms(html).values()
        for name, value in form.items() if name in _TIME_FIELDS}


class _NativeForm(HTMLParser):
    """Successful controls, including repeated rows and the clicked submit button."""

    def __init__(self, html, action, *, identity_fields=("csrf_token", "expected_row_version", "idempotency_key")):
        super().__init__()
        self.action = action
        self.fields = {}
        self.buttons = []
        self.active = False
        self.textarea = None
        self.select = None
        self.options = []
        self.feed(html)
        assert self.fields, f"Missing native form: {action}"
        # Reuse the shared hidden-field reader for the original command identity.
        hidden = hidden_post_forms(html)[action]
        for name in identity_fields:
            assert self.one(name) == hidden[name]

    def one(self, name):
        values = self.fields[name]
        assert len(values) == 1, (name, values)
        return values[0]

    def set(self, name, value):
        assert name in self.fields, f"The actual form does not expose {name}"
        self.fields[name] = [value] if isinstance(value, str) else value

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.active = attrs.get("action") == self.action and attrs.get("method", "").lower() == "post"
        if not self.active or "disabled" in attrs:
            return
        name = attrs.get("name")
        if tag == "input" and name:
            self._record_input(name, attrs)
            return
        if tag == "textarea" and name:
            self.textarea = name
            self.fields.setdefault(name, []).append("")
            return
        if tag == "select" and name:
            self.select, self.options = name, []
            return
        if tag == "option" and self.select:
            self.options.append((attrs.get("value", ""), "selected" in attrs))
            return
        if tag == "button" and attrs.get("type", "submit") == "submit":
            self.buttons.append(attrs)

    def _record_input(self, name, attrs):
        kind = attrs.get("type", "text")
        if kind in {"submit", "button", "reset"} or (kind in {"checkbox", "radio"} and "checked" not in attrs):
            return
        self.fields.setdefault(name, []).append(attrs.get("value", ""))

    def handle_data(self, data):
        if self.active and self.textarea:
            self.fields[self.textarea][-1] += data

    def handle_endtag(self, tag):
        if tag == "form":
            self.active = False
        elif tag == "textarea":
            self.textarea = None
        elif tag == "select" and self.select:
            selected = [value for value, chosen in self.options if chosen]
            self.fields.setdefault(self.select, []).append(selected[-1] if selected else self.options[0][0])
            self.select, self.options = None, []

    def post(self, client, *, rate=False, review=False, fetch=False):
        fields = deepcopy(self.fields)
        action = self.action
        if rate:
            candidates = [button for button in self.buttons
                if button.get("formaction", "").endswith("/correction-rate")
                and (button.get("name") == "fx_fetch_reference") == fetch
                and (button.get("name") == "fx_review_latest") == review]
            assert len(candidates) == 1, self.buttons
            button = candidates[0]
            action = button["formaction"]
            if button.get("name"):
                fields[button["name"]] = [button["value"]]
        return client.post(action, data=fields, headers={"Origin": str(client.base_url).rstrip("/")},
            follow_redirects=False)


def _ack_form_html(page_text: str, expense_id: int) -> str | None:
    marker = f'action="/web/expenses/{expense_id}/items/acknowledge-mismatch"'
    if marker not in page_text:
        return None
    marker_index = page_text.index(marker)
    start = page_text.rfind("<form", 0, marker_index)
    end = page_text.index("</form>", marker_index)
    return page_text[start:end]


def _hidden_value(form_html: str, name: str) -> str:
    match = re.search(rf'name="{re.escape(name)}" value="([^"]+)"', form_html)
    assert match is not None
    return match.group(1)
