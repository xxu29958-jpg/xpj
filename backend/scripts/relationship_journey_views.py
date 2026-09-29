"""Real history pagination, private-ledger boundaries and both appearances."""

import json
from contextlib import closing
from urllib.parse import parse_qs, urlsplit

from scripts.planning_journey_android import wait_for


def native_current_share(native, expected):
    # The agreement is the first detail item; its async insertion can leave
    # the viewport anchored to a later item that was already on screen.
    native.reveal_any("当前约定", toward_start=True)

    def current_matches():
        current = [node.attrib.get("text", "").split("当前约定", 1)[1]
            for node in native.tree().iter("node") if "当前约定" in node.attrib.get("text", "")]
        return any(value.strip() == f"¥{expected}" for value in current)

    wait_for(current_matches, f"The actual native detail did not read the current agreement {expected}")


def goal_entry(j, *, create=False):
    if create:
        j.goto("/web/debt-goals", receiver=True)
        j.receiver.get_by_text("新建还债目标", exact=True).click()
        form = j.receiver.locator('form[action="/web/debt-goals/create"]')
        form.locator('[name="name"]').fill("跟踪这笔原始往来")
        form.locator(f'[name="debt_public_ids"][value="{j.facts()["original_id"]}"]').check()
        form.get_by_role("button", name="创建目标", exact=True).click()
        j.receiver.locator('.plan-debt-goal[aria-label="还债目标：跟踪这笔原始往来"]').wait_for()
    native = j.native
    native.plan_home()
    native.click("还债目标")
    native.reveal_any("跟踪这笔原始往来")
    native.click("跟踪这笔原始往来")
    native.reveal_any("家庭成员")
    native.click("家庭成员", stable=True)
    native_current_share(native, "40.00" if create else "14.00")
    native.capture("relationship-goal-linked-" + ("initial" if create else "after-agreements"))


def web_history(j, public_id, name):
    j.goto(f"/web/debts/{public_id}")
    rows, pages = [], 0
    for _ in range(4):
        history = j.page.locator("#debt-activity")
        history.wait_for(state="visible")
        rows.extend(history.locator(".debt-history-row").evaluate_all(
            "rows => rows.map(row => ({id:row.id,text:row.innerText}))"))
        pages += 1
        j.capture(f"{name}-history-page-{pages}")
        following = history.get_by_role("link", name="下一页", exact=True)
        if not following.count():
            break
        following.click()
    else:
        raise AssertionError("The bounded relationship history did not finish within four pages")
    assert pages >= 2 and len({row["id"] for row in rows}) == len(rows), "History paging lost or duplicated a record"
    text = "\n".join(row["text"] for row in rows)
    assert all(title in text for title in ("提出新约定", "处理约定提议", "双方接受新约定"))
    assert "保留已付款和免除，明确返还三元" in text and "native-reopen-12" in text
    (j.evidence / f"web-relationship-{name}-history.json").write_text(
        json.dumps({"pages": pages, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")


def private_expense_boundary(j, current):
    j.goto(f"/web/debts/{current['return_id']}")
    assert j.identity.receiver_ledger not in j.page.inner_text("main")
    assert "接收方私有流水" not in j.page.inner_text("main")
    assert j.page.locator(f'a[href*="/web/expenses/{current["received_id"]}/edit"]').count() == 0
    path = f"/web/expenses/{current['received_id']}/edit"
    response = j.goto(path)
    # Full-page stale/cross-ledger links return to the current ledger with an
    # explanation; the drawer endpoint retains the underlying 404 status.
    final = urlsplit(j.page.url)
    assert response.status == 200 and final.path == "/web/confirmed"
    assert parse_qs(final.query).get("ledger_id") == [j.identity.sender_ledger]
    assert "没有找到这笔账单。" in j.page.inner_text("main")
    assert j.page.locator(f'a[href*="{path}"]').count() == 0
    j.capture("private-expense-refused")
    fragment = j.page.request.get(f"{j.base_url}{path}?fragment=1&ledger_id={j.identity.sender_ledger}")
    assert fragment.status == 404 and "没有找到这笔账单。" in fragment.text()
    foreign_ledger = j.page.request.get(f"{j.base_url}{path}?fragment=1&ledger_id={j.identity.receiver_ledger}")
    assert foreign_ledger.status == 403, "The sender entered the other party's private ledger"


def role_boundaries(j):
    current = j.facts()
    private_expense_boundary(j, current)
    for account, role in ((j.identity.observer_account, "unrelated-member"), (j.identity.viewer_account, "viewer")):
        with closing(j.page.context.browser.new_context(viewport={"width": 390, "height": 960})) as context:
            reader = context.new_page()
            j.connect(reader, account, next_path="/web/debts")
            for public_id in (current["original_id"], current["return_id"]):
                reader.goto(f"{j.public_url}/web/debts/{public_id}/split-agreement?ledger_id={j.identity.receiver_ledger}")
                assert "新约定仅由双方本人提出和处理" in reader.inner_text("main")
                assert not reader.locator("[data-repayment-submit]").is_visible()
                assert reader.locator(".product-page-title").inner_text() == "拆账新约定"
                reader.screenshot(path=j.evidence / f"web-relationship-{role}-{public_id}.png", full_page=True)


def appearances(j):
    current = j.facts()
    for receiver in (False, True):
        page = j.receiver if receiver else j.page
        for theme in ("paper", "midnight"):
            page.set_viewport_size({"width": 1280, "height": 960})
            j.goto(f"/web/debts/{current['original_id']}", receiver=receiver)
            page.locator("#appearance > summary").click()
            page.locator(f'#appearance [data-theme-mode="{theme}"]').click()
            page.wait_for_function("theme => document.documentElement.dataset.theme === theme", arg=theme)
            page.locator("#appearance > summary").click()
            for width in (1280, 390):
                page.set_viewport_size({"width": width, "height": 960})
                for name, public_id in (("original", current["original_id"]), ("return", current["return_id"])):
                    j.goto(f"/web/debts/{public_id}/split-agreement", receiver=receiver)
                    assert page.locator("html").get_attribute("data-theme") == theme
                    assert "当前约定份额" in page.inner_text("main") and "¥14.00" in page.inner_text("main")
                    j.capture(f"{'receiver' if receiver else 'sender'}-{name}-{width}-{theme}", receiver=receiver)
    native = j.native
    native.plan_home()
    native.click("打开账户与设置")
    native.click("外观与主题")
    native.click("玄夜")
    for returned in (False, True):
        j.open_native(returned=returned)
        native_current_share(native, "14.00")
        native.capture("relationship-" + ("return" if returned else "original") + "-midnight")


def native_read_recovery(j):
    native = j.native
    for offline in (False, True):
        if offline:
            native.connection(j.port, online=False)
            native.restart()
        for returned in (False, True):
            j.open_native(returned=returned)
            native.reveal_any("拆账约定与结算")
            if offline:
                native.reveal_any("离线保存")
            native_current_share(native, "14.00")
            native.capture(f"relationship-{'return' if returned else 'original'}-{'offline' if offline else 'fresh'}-facts")
            native.reveal_any("往来历史")
            native.reveal_any("提出拆账新约定", "新约定提议已处理", "达成拆账新约定")
            native.capture(f"relationship-{'return' if returned else 'original'}-{'offline' if offline else 'fresh'}-history")
            # A page has 20 expanded financial-history rows, each with amounts
            # and settlement evidence; the default form search covers 8 swipes.
            native.reveal_any("较早记录", max_scrolls=20)
            native.click("较早记录")
            native.capture(f"relationship-{'return' if returned else 'original'}-{'offline' if offline else 'fresh'}-older-history")
    native.connection(j.port, online=True)


def verify_views(j):
    goal_entry(j)
    for name, public_id in (("original", j.facts()["original_id"]), ("return", j.facts()["return_id"])):
        web_history(j, public_id, name)
    role_boundaries(j)
    appearances(j)
    native_read_recovery(j)
