"""Read the hidden fields a native browser would submit from server-rendered forms."""

from html.parser import HTMLParser


class _PostForms(HTMLParser):
    def __init__(self, html: str) -> None:
        super().__init__()
        self.forms: dict[str, dict[str, str]] = {}
        self.current: dict[str, str] | None = None
        self.feed(html)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "form" and values.get("method", "").lower() == "post":
            self.current = self.forms.setdefault(values.get("action", ""), {})
        if tag == "input" and self.current is not None and values.get("type") == "hidden":
            name = values.get("name")
            if name and "disabled" not in values:
                self.current[name] = values.get("value") or ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self.current = None


def hidden_post_forms(html: str) -> dict[str, dict[str, str]]:
    return _PostForms(html).forms
