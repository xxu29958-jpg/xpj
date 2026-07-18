"""Non-DB contracts for currency-aware Web templates and chart formatting."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "app" / "templates" / "web"
OWNER_TEMPLATES = ROOT / "app" / "templates" / "owner"
WEB_STATIC = ROOT / "app" / "static" / "web"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_money_templates_do_not_reintroduce_fixed_two_decimal_assumptions() -> None:
    surfaces = [
        TEMPLATES / "confirmed.html",
        TEMPLATES / "dashboard.html",
        TEMPLATES / "reports.html",
        TEMPLATES / "budgets.html",
        TEMPLATES / "budget_advise.html",
        TEMPLATES / "goals.html",
        TEMPLATES / "income_plans.html",
        TEMPLATES / "rules.html",
        TEMPLATES / "search.html",
        TEMPLATES / "import_batch.html",
        TEMPLATES / "edit.html",
        TEMPLATES / "_edit_drawer.html",
        TEMPLATES / "bill_splits_inbox.html",
        TEMPLATES / "bill_splits_sent.html",
    ]
    source = "\n".join(_read(path) for path in surfaces)

    banned = (
        "/ 100",
        "/100",
        "'%.2f'",
        '"%.2f"',
        'step="0.01"',
        'min="0.01"',
        'placeholder="0.00"',
        "（元",
    )
    assert not [token for token in banned if token in source]

    base = _read(TEMPLATES / "base.html")
    assert 'data-home-currency-minor-digits="{{ home_currency_input.minor_unit_digits }}">' in base
    reports = _read(TEMPLATES / "reports.html")
    assert "six_month_average_amount_label" in reports
    assert "_avg6" not in reports
    assert "round | int" not in reports
    confirmed = _read(TEMPLATES / "confirmed.html")
    assert "month_average_amount_label" in confirmed
    assert "month_total_amount_yuan / month_total_count" not in confirmed

    import_batch = _read(TEMPLATES / "import_batch.html")
    assert "row.amount_label" in import_batch
    assert "home_amount_label(row.amount_cents)" not in import_batch

    import_help = _read(TEMPLATES / "import_export.html")
    assert "始终按两位小数解析并乘以" in import_help
    assert "<code>original_currency_code</code>" in import_help
    assert "<code>original_amount_minor</code>" in import_help
    assert "缺少原币金额时会拒绝导入" in import_help


def test_shells_show_home_currency_context_next_to_ledger_name() -> None:
    base = _read(TEMPLATES / "base.html")
    switcher = _read(TEMPLATES / "_ledger_switcher.html")
    owner = _read(OWNER_TEMPLATES / "index.html")
    assert "{{ selected_ledger_name }} · {{ home_currency_code }}" in base
    assert "_ledger_kind }} · {{ home_currency_code }}" in switcher
    assert "budget_status.ledger_name }} · {{ home_currency_code }}" in owner


def test_forms_bind_metadata_to_the_currency_that_owns_the_amount() -> None:
    home_forms = "\n".join(
        _read(TEMPLATES / name)
        for name in (
            "budgets.html",
            "budget_advise.html",
            "goals.html",
            "income_plans.html",
            "rules.html",
        )
    )
    for field in (
        "home_currency_input.amount_step",
        "home_currency_input.inputmode",
        "home_currency_input.amount_input_hint",
    ):
        assert field in home_forms

    edit = _read(TEMPLATES / "edit.html")
    drawer = _read(TEMPLATES / "_edit_drawer.html")
    assert "expense.original_currency_input.amount_step" in edit
    assert "e.original_currency_input.amount_step" in drawer
    assert "expense_currency_input.amount_step" in edit
    assert "split_invite.currency_input.amount_step" in edit
    assert "split_invite.remaining_label" in edit

    bill_split_lists = _read(TEMPLATES / "bill_splits_inbox.html") + _read(TEMPLATES / "bill_splits_sent.html")
    assert bill_split_lists.count("row.amount_label") == 2
    assert bill_split_lists.count("row.currency_code") == 2
    assert "home_currency_symbol }}{{ row.amount_yuan" not in bill_split_lists


def test_chart_scripts_format_money_from_home_currency_minor_digits() -> None:
    scripts = "\n".join(
        _read(WEB_STATIC / path)
        for path in (
            "reports.js",
            "desktop/core.js",
            "desktop/category-donut.js",
            "desktop/dashboard.js",
            "desktop/trend-chart.js",
            "desktop/sparks.js",
        )
    )
    assert "data-home-currency-minor-digits" in scripts
    assert "/ 100" not in scripts
    assert "/100" not in scripts
    assert "toFixed(2)" not in scripts
    assert "minimumFractionDigits: 2" not in scripts
    assert "maximumFractionDigits: 2" not in scripts
    assert "amount_major" in scripts
    assert "amount_value" in scripts


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is unavailable")
def test_shared_web_money_runtime_distinguishes_cny_jpy_and_krw() -> None:
    core_path = WEB_STATIC / "desktop" / "core.js"
    script = r"""
const fs = require("fs");
const attrs = {};
global.window = {};
global.document = {
  documentElement: {
    getAttribute(name) {
      return Object.prototype.hasOwnProperty.call(attrs, name) ? attrs[name] : null;
    },
  },
};
global.getComputedStyle = function () {
  return { getPropertyValue() { return ""; } };
};
eval(fs.readFileSync(process.argv[1], "utf8"));
const app = global.window.TicketboxWeb;
const cases = [
  { code: "CNY", symbol: "¥", digits: "2", minor: 1234, money: "¥12.34", parts: ["12", "34"] },
  { code: "JPY", symbol: "¥", digits: "0", minor: 1234, money: "¥1,234", parts: ["1234", ""] },
  { code: "KRW", symbol: "₩", digits: "0", minor: 1234, money: "₩1,234", parts: ["1234", ""] },
];
for (const item of cases) {
  attrs["data-home-currency"] = item.code;
  attrs["data-home-currency-symbol"] = item.symbol;
  attrs["data-home-currency-minor-digits"] = item.digits;
  const money = app.homeMoneyMinor(item.minor);
  const parts = app.moneyParts(item.digits === "0" ? "1234" : "12.34");
  if (money !== item.money || JSON.stringify(parts) !== JSON.stringify(item.parts)) {
    throw new Error(JSON.stringify({ item, money, parts }));
  }
}
"""
    completed = subprocess.run(
        ["node", "-e", script, str(core_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
