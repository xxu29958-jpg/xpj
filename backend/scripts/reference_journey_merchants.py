"""The directory and aliases keep historical expense merchant facts intact."""

from scripts.planning_journey_android import wait_for


def organize_merchants(j):
    native, page = j.native, j.page
    j.native_open("商家")
    native.click("新增商家")
    native.fill("RefShop", label="商家名称")
    native.click("添加商家")
    j.expect(lambda state: any(row["name"] == "RefShop" for row in state["catalog"]),
             "The native merchant catalog creation did not commit")
    native.click("新增别名")
    native.fill("RefShop", label="标准商家名")
    native.fill("RefPay", label="别名")
    native.click("添加别名")
    j.expect(lambda state: any(row["alias"] == "RefPay" and row["canonical"] == "RefShop" for row in state["aliases"]),
             "The native merchant alias did not reach the shared owner")
    j.goto("/web/merchants")
    assert "RefPay" in page.inner_text("main") and "RefShop" in page.inner_text("main")
    create = j.form("/web/merchants/catalog/create")
    create.locator('[name="display_name"]').fill("OldShop")
    create.get_by_role("button", name="添加商家", exact=True).click()
    j.expect(lambda state: any(row["name"] == "OldShop" for row in state["catalog"]), "The Web merchant was not retained")
    source = next(row for row in j.facts()["catalog"] if row["name"] == "OldShop")
    target = next(row for row in j.facts()["catalog"] if row["name"] == "RefShop")
    merge = j.form(f'/web/merchants/catalog/{source["id"]}/merge')
    merge.locator('[name="target"]').select_option(f'{target["id"]}:{target["row_version"]}')
    merge.locator('[name="alias_policy"]').select_option("none")
    j.confirm(merge)
    j.expect(lambda state: any(row["id"] == source["id"] and row["target"] == target["id"] for row in state["catalog"]),
             "The explicit Web merchant merge did not commit")
    assert len(j.facts()["aliases"]) == 1, "The no-alias choice silently created a new alias"
    assert all(row["merchant"] == "RefPay" for row in j.facts()["expenses"]), "The directory rewrote historical merchant facts"
    j.capture("merchant-merge-keeps-original-facts")
    alias = j.facts()["aliases"][0]
    j.confirm(j.form(f'/web/merchants/aliases/{alias["id"]}/delete'))
    j.expect(lambda state: state["aliases"][0]["deleted"], "The Web alias removal did not commit")
    # Navigating through the actual library takes longer than the short undo banner;
    # the shared recycle owner, rather than that transient banner, restores the row.
    j.native_open("回收站")
    native.reveal_any("RefPay")
    native.capture("reference-alias-in-shared-recycle")
    native.click_within("RefPay", "恢复")
    native.click_within("恢复项目？", "恢复")
    j.expect(lambda state: not state["aliases"][0]["deleted"], "The actual native recycle bin did not restore the alias")
    wait_for(lambda: not native.has("RefPay"), "The restored alias remained in the recycle bin")
    j.goto("/web/merchants")
    assert "RefPay" in page.inner_text("main")
    j.capture("merchant-alias-restored-from-native")
