"""The directory and aliases keep historical expense merchant facts intact."""

from scripts.planning_journey_android import wait_for


def organize_merchants(j):
    create_catalog_and_alias(j)
    merge_after_target_changes(j)
    restore_alias(j)


def create_catalog_and_alias(j):
    native, page = j.native, j.page
    j.native_open("商家")
    native.click("新增商家")
    native.fill("RefShop", label="商家名称")
    native.click("添加商家")
    j.expect(lambda state: any(row["name"] == "RefShop" for row in state["catalog"]),
             "The native merchant catalog creation did not commit")
    native.click("RefShop")
    native.click("新增别名")
    native.fill("RefShop", label="标准商家名")
    native.fill("RefPay", label="别名")
    native.click("添加别名")
    j.expect(lambda state: any(row["alias"] == "RefPay" and row["canonical"] == "RefShop" for row in state["aliases"]),
             "The native merchant alias did not reach the shared owner")
    j.goto("/web/merchants")
    page.get_by_role("link", name="RefShop", exact=True).click()
    assert "RefPay" in page.inner_text("main") and "RefShop" in page.inner_text("main")


def merge_after_target_changes(j):
    j.page.get_by_role("link", name="商家目录", exact=True).click()
    j.page.get_by_role("link", name="添加商家", exact=True).click()
    create = j.form("/web/merchants/catalog/create")
    create.locator('[name="display_name"]').fill("OldShop")
    create.get_by_role("button", name="添加商家", exact=True).click()
    j.expect(lambda state: any(row["name"] == "OldShop" for row in state["catalog"]), "The Web merchant was not retained")
    source = next(row for row in j.facts()["catalog"] if row["name"] == "OldShop")
    target = next(row for row in j.facts()["catalog"] if row["name"] == "RefShop")
    j.page.get_by_role("link", name="OldShop", exact=True).click()
    j.page.get_by_text("合并到另一个商家", exact=True).click()
    action = f'/web/merchants/catalog/{source["id"]}/merge'
    merge = j.form(action)
    original_target = f'{target["id"]}:{target["row_version"]}'
    original_version = merge.locator('[name="expected_row_version"]').input_value()
    merge.locator('[name="target"]').select_option(original_target)
    merge.locator('[name="alias_policy"]').select_option("none")
    change_catalog_visibility(j, target)
    j.confirm(merge)
    retained = j.form(action)
    assert retained.locator('[name="target"]').input_value() == original_target, "The failed merchant merge lost its target"
    assert retained.locator('[name="alias_policy"]').input_value() == "none", "The failed merchant merge changed the user's alias choice"
    assert retained.locator('[name="expected_row_version"]').input_value() == original_version
    assert next(row for row in j.facts()["catalog"] if row["id"] == source["id"])["target"] is None
    j.capture("merchant-conflict-keeps-original-choices")
    current = next(row for row in j.facts()["catalog"] if row["id"] == target["id"])
    retained.get_by_role("button", name="核对双方商家", exact=True).click()
    retained = j.form(action)
    assert retained.locator('[name="target"]').input_value() == f'{target["id"]}:{current["row_version"]}'
    assert next(row for row in j.facts()["catalog"] if row["id"] == source["id"])["target"] is None
    j.confirm(retained)
    j.expect(lambda state: any(row["id"] == source["id"] and row["target"] == target["id"] for row in state["catalog"]),
             "The explicit Web merchant merge did not commit")
    assert len(j.facts()["aliases"]) == 1, "The no-alias choice silently created a new alias"
    assert all(row["merchant"] == "RefPay" for row in j.facts()["expenses"]), "The directory rewrote historical merchant facts"
    j.capture("merchant-merge-keeps-original-facts")


def change_catalog_visibility(j, target):
    # A second consumer changes the target while the original Web form stays open.
    # Hide/show preserves its name and the separate alias used by the rule journey.
    j.native.click("商家身份")
    for choice, status in (("隐藏", "hidden"), ("显示", "active")):
        j.native.click(choice)
        j.native.click_within("显示与隐藏", choice)
        j.expect(lambda state, status=status: any(row["id"] == target["id"] and row["status"] == status for row in state["catalog"]),
                 "The native target change did not commit")


def restore_alias(j):
    native, page = j.native, j.page
    alias = j.facts()["aliases"][0]
    page.get_by_role("link", name="全部别名", exact=False).click()
    j.confirm(j.form(f'/web/merchants/aliases/{alias["id"]}/delete'))
    j.expect(lambda state: state["aliases"][0]["deleted"], "The Web alias removal did not commit")
    # Navigating through the actual library takes longer than the short undo banner;
    # the shared recycle owner, rather than that transient banner, restores the row.
    j.native_open("回收站")
    native.reveal_any("RefPay")
    native.capture("reference-alias-in-shared-recycle")
    native.click("恢复 RefPay")
    native.click_within("恢复项目？", "恢复")
    j.expect(lambda state: not state["aliases"][0]["deleted"], "The actual native recycle bin did not restore the alias")
    wait_for(lambda: not native.has("RefPay"), "The restored alias remained in the recycle bin")
    j.goto("/web/merchants")
    page.get_by_role("link", name="全部别名", exact=False).click()
    assert "RefPay" in page.inner_text("main")
    j.capture("merchant-alias-restored-from-native")
