"""Verify financial contributions through actual query consumers and appearances."""

import hashlib

from scripts.planning_journey_android import wait_for


def _configure_plans(j):
    state = j.facts()
    if not state["budget_configured"]:
        j.goto(f'/web/budgets?month={state["month"]}')
        form = j.form("/web/budgets/save")
        if not form.locator('[name="total_amount_yuan"]').is_visible():
            form.locator("xpath=ancestor::details").locator("summary").click()
        form.locator('[name="total_amount_yuan"]').fill("100.00")
        form.locator("[data-budget-submit]").click()
        j.expect(lambda value: value["budget_configured"], "The real budget form did not commit")
    if not state["goals"]:
        j.goto(f'/web/goals?month={state["month"]}')
        form = j.form("/web/goals/create")
        if not form.locator('[name="name"]').is_visible():
            form.locator("xpath=ancestor::details").locator("summary").click()
        form.locator('[name="name"]').fill("FactCap")
        form.locator('[name="target_amount_yuan"]').fill("100.00")
        form.locator('button[type="submit"]:not([name])').click()
        j.expect(lambda value: len(value["goals"]) == 1, "The real consumer goal did not commit")


def _original(j):
    j.goto(f'/web/expenses/{j.facts()["id"]}/original')
    link = j.page.get_by_role("link", name="下载原图", exact=True)
    response = j.page.request.get(j.base_url + link.get_attribute("href"))
    assert response.ok and hashlib.sha256(response.body()).hexdigest() == j.original_digest, (
        "The authenticated original no longer matches its recorded bytes")
    j.page.get_by_role("button", name="打开实际原图", exact=True).click()
    image = j.page.locator("[data-original-reviewed-image]")
    wait_for(lambda: image.is_visible() and image.evaluate("image => image.complete && image.naturalWidth > 0"),
        "The authenticated original did not render its actual image bytes")
    j.capture("original-after-financial-changes")


def consumers(j, *, expected_net):
    _configure_plans(j)
    state = j.facts()
    assert state["net"] == state["budget_spent"] == state["stats_spent"] == expected_net
    assert state["goals"] == [{"name": "FactCap", "spent": expected_net}]
    amount = f"{expected_net // 100}.{expected_net % 100:02d}"
    for path in ("budgets", "goals", "reports", "overview"):
        j.goto(f'/web/{path}?month={state["month"]}')
        assert amount in j.page.inner_text("main"), f"The actual {path} consumer missed the financial net"
        j.capture(f"{path}-net-{expected_net}")
    j.goto(f'/web/confirmed?month={state["month"]}')
    assert "WebFinal" in j.page.inner_text("main")
    j.capture(f"ledger-net-{expected_net}")
    j.goto("/web/data-quality")
    assert "数据质量" in j.page.inner_text("main")
    j.capture(f"quality-after-{expected_net}")
    _original(j)
    assert j.facts() == state, "Reading downstream consumers mutated financial facts"
    native = j.native
    native.plan_home()
    native.reveal_any(amount)
    native.capture(f"financial-plan-net-{expected_net}")
    native.click("消费目标")
    native.click("FactCap")
    native.reveal_any(amount)
    native.capture(f"financial-goal-net-{expected_net}")
    native.domain_home("洞察")
    native.reveal_any(amount)
    native.capture(f"financial-insights-net-{expected_net}")
    j.native_open()
    native.reveal_any(amount)
    native.capture(f"financial-fact-net-{expected_net}")


def appearances(j):
    page, native = j.page, j.native
    expense_id = j.facts()["id"]
    for theme in ("paper", "midnight"):
        page.set_viewport_size({"width": 1280, "height": 960})
        j.goto(f"/web/expenses/{expense_id}/edit")
        page.locator("#appearance > summary").click()
        page.locator(f'#appearance [data-theme-mode="{theme}"]').click()
        wait_for(lambda theme=theme: page.locator("html").get_attribute("data-theme") == theme,
            "The actual financial page did not apply its selected theme")
        page.locator("#appearance > summary").click()
        for width in (1280, 390):
            page.set_viewport_size({"width": width, "height": 960})
            for suffix in ("edit", "correct"):
                j.goto(f"/web/expenses/{expense_id}/{suffix}")
                assert page.locator("html").get_attribute("data-theme") == theme
                j.capture(f"{suffix}-{width}-{theme}")
        native.plan_home()
        native.click("打开账户与设置")
        native.click("外观与主题")
        native.click("温润米白 + 茶铜" if theme == "paper" else "深色玻璃 + 暖金")
        j.native_open()
        native.capture("financial-fact-" + theme)
        native.reveal_any("查看已送达的更正（2）", toward_start=True)
        native.click("查看已送达的更正（2）")
        native.reveal_any("原因：NativeDraft")
        native.reveal_any("原因：NativeNote")
        native.capture("financial-original-submissions-" + theme)
        native.reveal_any("收起已送达的更正（2）", toward_start=True)
        native.click("收起已送达的更正（2）")
        native.reveal_any("WebDraft")
        native.capture("financial-history-" + theme)
        native.reveal_any("更正这笔账单", toward_start=True)
        native.click("更正这笔账单")
        wait_for(lambda: native.has("更正原因（必填）"), "The themed correction editor did not open")
        native.capture("financial-correction-" + theme)
        native.click("保留原稿并关闭")
