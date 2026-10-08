"""Rule definition, preview, explicit application and partial recovery stay distinct."""

from scripts.planning_journey_android import wait_for


def organize_rules(j):
    initial_categories = [row["category"] for row in j.facts()["expenses"]]
    original_rules = j.facts()["rules"]
    category, rule = create_rule(j, initial_categories, original_rules)
    resume_rule_edit(j, initial_categories, rule)
    preview_apply_and_rollback(j, initial_categories)
    apply_and_rollback_from_native(j)
    restore_rule_and_category(j, category, rule)
    assert [row for row in j.facts()["rules"] if row["id"] != rule["id"]] == original_rules, "The journey changed an existing rule"


def create_rule(j, initial_categories, original_rules):
    page = j.page
    j.goto("/web/rules")
    page.get_by_role("link", name="添加规则", exact=True).click()
    create = j.form("/web/rules/create")
    create.locator('[name="keyword"]').fill("RefShop")
    create.locator('[name="category"]').fill("Library")
    create.get_by_role("button", name="添加规则", exact=True).click()
    j.expect(lambda state: len(state["rules"]) == len(original_rules) + 1, "The actual Web rule was not retained")
    rule = next(row for row in j.facts()["rules"] if row["keyword"] == "RefShop")
    assert rule["category"] == "Library" and rule["priority"] == 100 and not rule["deleted"]
    assert [row["category"] for row in j.facts()["expenses"]] == initial_categories

    category = next(row for row in j.facts()["categories"] if row["name"] == "Library")
    j.goto("/web/categories")
    page.locator(f'#category-{category["id"]} > a').click()
    assert "RefShop" in page.get_by_role("navigation", name="使用此分类的配置").inner_text()
    assert j.form(f'/web/categories/preferences/{category["id"]}/delete').count() == 0
    assert "Library" in page.inner_text("main") and "规则" in page.inner_text("main")
    assert not next(row for row in j.facts()["categories"] if row["id"] == category["id"])["deleted"]
    j.capture("category-reference-blocks-delete")
    return category, rule


def resume_rule_edit(j, initial_categories, rule):
    native = j.native
    j.native_open("分类规则")
    # The real installation includes its default rules. Locate this new rule
    # in that full list instead of treating it as the first/only database row.
    native.reveal_any("RefShop", max_scrolls=16)
    j.native_row_action("RefShop", "分类规则操作")
    native.click("编辑")
    native.reveal_any("让分类更省心", toward_start=True, max_scrolls=16)
    native.fill("101", label="优先级")
    native.connection(j.port, online=False)
    try:
        native.click("保存规则")
        native.reveal_any("这份规则提交尚未确认", toward_start=True, max_scrolls=16)
        native.restart()
        j.native_open("分类规则")
        native.reveal_any("这份规则提交尚未确认")
        assert native.has("RefShop"), "The reopened submission lost its original rule"
        native.reveal_any("重新读取规则")
        assert native.has("规则暂时打不开"), "A failed rule read was presented as an empty dictionary"
        native.reveal_any("重新读取应用记录")
        assert native.has("应用记录暂时打不开"), "A failed history read was presented as an empty history"
        native.capture("reference-rule-offline-reopened")
        native.reveal_any("这份规则提交尚未确认", toward_start=True)
        assert j.rule(rule["id"])["priority"] == 100
    finally:
        native.connection(j.port, online=True)
    if native.has("重试原提交"):
        native.click("重试原提交")
    j.expect(lambda state: any(row["id"] == rule["id"] and row["priority"] == 101 for row in state["rules"]),
             "The original persisted rule edit did not resume")
    native.reveal_any("重新读取应用记录", max_scrolls=16)
    native.click("重新读取应用记录")
    native.reveal_any("还没有应用记录。")
    assert not j.facts()["applications"], "Retrying a history read replayed an application"
    native.capture("reference-rule-history-read-recovered")
    assert [row["category"] for row in j.facts()["expenses"]] == initial_categories


def preview_apply_and_rollback(j, initial_categories):
    native, page = j.native, j.page
    native.reveal_any("已入账应用", max_scrolls=16)
    native.click("预览")
    native.reveal_any("可更新 2 笔")
    assert not j.facts()["applications"] and not j.facts()["rule_changes"], "Preview wrote an application"
    native.capture("reference-rule-native-preview")
    j.goto("/web/rules")
    page.get_by_role("link", name="预览已确认账单").click()
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
    j.native_open("分类规则")
    native.reveal_any("回退", max_scrolls=16)
    native.click("回退")
    native.click_within("回退这次应用？", "回退")
    j.expect(lambda state: state["applications"][0]["status"] == "rollback_partial", "The actual native partial rollback did not finish")
    assert [row["category"] for row in j.facts()["expenses"]] == ["Manual", "其他", "Library"]
    native.reveal_any("部分回退", max_scrolls=16)
    native.capture("reference-rule-partial-rollback")
    j.goto("/web/rules")
    page.get_by_role("link", name="规则应用记录").click()
    assert "部分回退" in page.inner_text("main")
    assert "已恢复 1 笔 · 跳过 1 笔" in page.inner_text("main")
    j.capture("rule-partial-rollback-from-native")


def apply_and_rollback_from_native(j):
    native = j.native
    native.reveal_any("已入账应用", toward_start=True, max_scrolls=16)
    native.click("预览")
    native.reveal_any("可更新 1 笔")
    native.click("确认应用")
    j.expect(lambda state: len(state["applications"]) == 2, "The actual native application was not recorded")
    assert [row["category"] for row in j.facts()["expenses"]] == ["Manual", "Library", "Library"]
    native.reveal_any("已更新 1 笔")
    native.reveal_any("确认应用")
    controls = [node for node in native.tree().iter("node") if node.get("clickable") == "true" and
                any(child.get("text") == "确认应用" for child in node.iter("node"))]
    assert len(controls) == 1 and controls[0].get("enabled") == "false", "An accepted result still offers its old confirmation"
    native.capture("reference-rule-native-accepted")
    native.reveal_any("最近应用记录", max_scrolls=16)
    native.click("回退")
    native.click_within("回退这次应用？", "回退")
    j.expect(lambda state: state["applications"][1]["status"] == "rolled_back", "The native application could not be rolled back")
    assert [row["category"] for row in j.facts()["expenses"]] == ["Manual", "其他", "Library"]
    native.reveal_any("已回退")
    native.capture("reference-rule-native-application-rolled-back")


def restore_rule_and_category(j, category, rule):
    native, page = j.native, j.page
    j.goto("/web/rules")
    j.confirm(j.form(f'/web/rules/{rule["id"]}/delete'))
    j.expect(lambda state: any(row["id"] == rule["id"] and row["deleted"] for row in state["rules"]),
             "The Web rule delete did not commit")
    j.goto("/web/categories")
    page.locator(f'#category-{category["id"]} > a').click()
    j.confirm(j.form(f'/web/categories/preferences/{category["id"]}/delete'))
    j.expect(lambda state: next(row for row in state["categories"] if row["id"] == category["id"])["deleted"],
             "The now-unreferenced custom category could not be removed")
    assert j.facts()["expenses"][2]["category"] == "Library", "Removing an option rewrote historical facts"
    j.native_open("回收站")
    for label in ("Library", "RefShop"):
        native.reveal_any(label)
        j.native.click(f"恢复 {label}")
        native.click_within("恢复项目？", "恢复")
        wait_for(lambda label=label: not any(node.get("text") == label for node in native.tree().iter("node")),
                 "The restored reference row remained in the actual recycle bin")
    assert not j.rule(rule["id"])["deleted"]
    assert not next(row for row in j.facts()["categories"] if row["id"] == category["id"])["deleted"]
    j.goto("/web/rules")
    assert "RefShop" in page.inner_text("main")
    page.get_by_role("link", name="规则应用记录").click()
    assert "部分回退" in page.inner_text("main")
    assert "已恢复 1 笔 · 跳过 1 笔" in page.inner_text("main")
