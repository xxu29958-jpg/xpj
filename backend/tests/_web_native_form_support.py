"""Read the hidden fields a native browser would submit from server-rendered forms."""

from html.parser import HTMLParser

_TIME_FIELDS = {"time_precision", "calendar_revision", "user_local_date", "source_timezone",
    "source_utc_offset_seconds", "accounting_date", "expense_time", "spent_at"}


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
        if tag == "input" and self.current is not None and (
            values.get("type") == "hidden" or values.get("name") in _TIME_FIELDS
        ):
            name = values.get("name")
            if name and "disabled" not in values:
                self.current[name] = values.get("value") or ""
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
    """Hidden identity plus the indivisible native accounting-time controls."""
    return _PostForms(html).forms


def accounting_time_fields(html: str) -> dict[str, str]:
    return {name: value for form in hidden_post_forms(html).values()
        for name, value in form.items() if name in _TIME_FIELDS}
