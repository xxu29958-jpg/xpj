"""Rule definition, preview, explicit application and partial recovery stay distinct."""

from scripts.planning_journey_android import wait_for


def organize_rules(j):
    initial_categories = [row["category"] for row in j.facts()["expenses"]]
    category = create_rule(j, initial_categories)
    resume_rule_edit(j, initial_categories)
    preview_apply_and_rollback(j, initial_categories)
    restore_rule_and_category(j, category)


def create_rule(j, initial_categories):
    page = j.page
    j.goto("/web/rules")
    create = j.form("/web/rules/create")
    create.locator('[name="keyword"]').fill("RefShop")
    create.locator('[name="category"]').fill("Library")
    create.get_by_role("button", name="添加规则", exact=True).click()
    j.expect(lambda state: len(state["rules"]) == 1, "The actual Web rule was not retained")
    assert [row["category"] for row in j.facts()["expenses"]] == initial_categories

    category = next(row for row in j.facts()["categories"] if row["name"] == "Library")
    j.goto("/web/categories")
    j.confirm(j.form(f'/web/categories/preferences/{category["id"]}/delete'))
    assert "Library" in page.inner_text("main") and "规则" in page.inner_text("main")
    assert not next(row for row in j.facts()["categories"] if row["id"] == category["id"])["deleted"]
    j.capture("category-reference-blocks-delete")
    return category


def resume_rule_edit(j, initial_categories):
    native = j.native
    j.native_open("自动规则")
    native.reveal_any("RefShop")
    j.native_row_action("RefShop", "分类规则操作")
    native.click("编辑")
    native.fill("101", label="优先级")
    native.connection(j.port, online=False)
    try:
        native.click("保存规则")
        wait_for(lambda: native.has("这份规则提交尚未确认"), "The original rule edit was not retained offline")
        native.restart()
        j.native_open("自动规则")
        native.reveal_any("这份规则提交尚未确认")
        assert native.has("RefShop"), "The reopened submission lost its original rule"
        native.capture("reference-rule-offline-reopened")
        assert j.facts()["rules"][0]["priority"] == 100
    finally:
        native.connection(j.port, online=True)
    if native.has("重试原提交"):
        native.click("重试原提交")
    j.expect(lambda state: state["rules"][0]["priority"] == 101, "The original persisted rule edit did not resume")
    assert len(j.facts()["rules"]) == 1 and [row["category"] for row in j.facts()["expenses"]] == initial_categories


def preview_apply_and_rollback(j, initial_categories):
    native, page = j.native, j.page
    native.reveal_any("已入账应用")
    native.click("预览")
    native.reveal_any("可更新 2 笔")
    assert not j.facts()["applications"] and not j.facts()["rule_changes"], "Preview wrote an application"
    native.capture("reference-rule-native-preview")
    j.goto("/web/rules")
    page.get_by_role("button", name="预览已确认影响", exact=True).click()
    assert [row["category"] for row in j.facts()["expenses"]] == initial_categories
    j.capture("rule-web-preview")
    j.confirm(j.form("/web/rules/apply-confirmed"))
    j.expect(lambda state: len(state["applications"]) == 1, "Explicit rule application was not recorded")
    assert [row["category"] for row in j.facts()["expenses"]] == ["Library", "Library", "Library"]
    assert j.facts()["applications"][0]["changed"] == 2
    assert len(j.facts()["rule_changes"]) == 2
    first = j.facts()["expenses"][0]["id"]
    j.batch([first], "category", "Manual")
    native.restart()
    j.native_open("自动规则")
    native.reveal_any("回退")
    native.click("回退")
    native.click_within("回退这次应用？", "回退")
    j.expect(lambda state: state["applications"][0]["status"] == "rollback_partial", "The actual native partial rollback did not finish")
    assert [row["category"] for row in j.facts()["expenses"]] == ["Manual", "其他", "Library"]
    native.capture("reference-rule-partial-rollback")
    j.goto("/web/rules")
    assert "部分回滚" in page.inner_text("main")
    j.capture("rule-partial-rollback-from-native")


def restore_rule_and_category(j, category):
    native, page = j.native, j.page
    rule = j.facts()["rules"][0]
    j.confirm(j.form(f'/web/rules/{rule["id"]}/delete'))
    j.expect(lambda state: state["rules"][0]["deleted"], "The Web rule delete did not commit")
    j.goto("/web/categories")
    j.confirm(j.form(f'/web/categories/preferences/{category["id"]}/delete'))
    j.expect(lambda state: next(row for row in state["categories"] if row["id"] == category["id"])["deleted"],
             "The now-unreferenced custom category could not be removed")
    assert j.facts()["expenses"][2]["category"] == "Library", "Removing an option rewrote historical facts"
    j.native_open("回收站")
    for label in ("Library", "RefShop"):
        native.reveal_any(label)
        native.click_within(label, "恢复")
        native.click_within("恢复项目？", "恢复")
        wait_for(lambda label=label: not native.has(label), "The restored reference remained in the actual recycle bin")
    assert not j.facts()["rules"][0]["deleted"]
    assert not next(row for row in j.facts()["categories"] if row["id"] == category["id"])["deleted"]
    j.goto("/web/rules")
    assert "RefShop" in page.inner_text("main") and "部分回滚" in page.inner_text("main")
