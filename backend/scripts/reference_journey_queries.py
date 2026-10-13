"""The public native consumer edits a Web-created query and reads later Web changes."""

from urllib.parse import parse_qs, urlsplit

from scripts.planning_journey_android import wait_for


def open_queries(j):
    j.native.domain_home("流水")
    j.native.click("找一笔账")
    j.native.click("常用查询")


def saved_queries(j):
    native, page = j.native, j.page
    original = j.facts()["views"][0]
    financial_before = j.facts()["expenses"]
    open_queries(j)
    native.click(original["name"])
    native.reveal_any("找到 1 条流水")
    native.capture("saved-query-web-created-native-result")
    native.click("修改条件或名称")
    native.fill("TripNative", previous=original["name"])
    native.fill("RefPay", previous="", label="关键词")
    native.click("保存这组查询")
    j.expect(lambda state: state["views"][0]["name"] == "TripNative" and state["views"][0]["query_text"] == "RefPay",
        "The actual native query edit did not reach the shared saved-query owner")
    native.click("完成并读取当前查询")
    j.goto(f'/web/saved-views/{original["id"]}/open')
    assert page.locator(".row-check").count() == 1
    assert parse_qs(urlsplit(page.url).query)["q"] == ["RefPay"]
    j.capture("saved-query-native-edit-read-by-web")

    j.goto(f'/web/saved-views?edit={original["id"]}')
    form = j.form(f'/web/saved-views/{original["id"]}/rename')
    form.locator('[name="name"]').fill("TripWebLater")
    form.locator('[name="category"]').fill("Library")
    form.get_by_role("button", name="保存更改", exact=True).click()
    j.expect(lambda state: state["views"][0]["name"] == "TripWebLater" and state["views"][0]["category"] == "Library",
        "The later Web query edit did not commit")
    native.restart()
    open_queries(j)
    native.click("TripWebLater")
    native.reveal_any("没有符合这些条件的流水")
    native.capture("saved-query-current-conditions-after-process-restart")
    assert j.facts()["expenses"] == financial_before, "Saving a query changed financial facts"

    # Leave the original shared query useful for the remaining role/appearance journey.
    j.goto(f'/web/saved-views?edit={original["id"]}')
    form = j.form(f'/web/saved-views/{original["id"]}/rename')
    form.locator('[name="category"]').fill("")
    form.get_by_role("button", name="保存更改", exact=True).click()
    wait_for(lambda: j.facts()["views"][0]["category"] == "", "The shared query did not restore its original category range")
    assert j.facts()["expenses"] == financial_before
