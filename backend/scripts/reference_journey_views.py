"""Actual member/viewer consumers, ledger switching and the shipped appearances."""

from contextlib import closing

from scripts.planning_journey_android import wait_for
from scripts.planning_journey_roles import _member_code
from scripts.reference_journey_facts import facts

PAGES = ("categories", "merchants", "tags", "rules", "saved-views", "recycle-bin")


def connect(page, j, role):
    public_url = j.base_url.replace("127.0.0.1", "localhost")
    page.goto(public_url + "/web/auth/login?next=/web/tags")
    page.locator('[name="pairing_code"]').fill(_member_code(j.fixture.ledger_id, role))
    page.locator('form[action="/web/auth/login"] button[type="submit"]').click()
    page.wait_for_url("**/web/tags*")
    return public_url


def roles(j):
    original = j.tag("TripNew")
    with closing(j.page.context.browser.new_context()) as context:
        member = context.new_page()
        connect(member, j, "member")
        form = member.locator(f'form[action="/web/tags/{original["id"]}/rename"]')
        form.locator('[name="name"]').fill("TripFinal")
        form.get_by_role("button", name="重命名", exact=True).click()
        j.expect(lambda state: any(row["name"] == "TripFinal" and row["id"] == original["id"] for row in state["tags"]),
                 "The real member edit did not reach the shared tag")
        member.screenshot(path=j.evidence / "web-reference-member-rename.png", full_page=True)
    with closing(j.page.context.browser.new_context()) as context:
        viewer = context.new_page()
        public_url = connect(viewer, j, "viewer")
        for path in PAGES:
            viewer.goto(f"{public_url}/web/{path}?ledger_id={j.fixture.ledger_id}")
            assert "只读" in viewer.inner_text("main"), f"The {path} page did not explain the viewer's role"
            assert viewer.locator('main form[method="post"]').count() == 0, f"The viewer can initiate a write from {path}"
        view = j.facts()["views"][0]
        viewer.goto(f'{public_url}/web/saved-views/{view["id"]}/open?ledger_id={j.fixture.ledger_id}')
        assert "TripFinal" in viewer.inner_text("main")
        # A stale/forged command still reaches the real server's role check.
        csrf = viewer.locator('meta[name="csrf-token"]').get_attribute("content")
        response = context.request.post(f'{public_url}/web/tags/{original["id"]}/rename',
            form={"ledger_id": j.fixture.ledger_id, "expected_row_version": str(j.tag("TripFinal")["row_version"]),
                  "name": "ViewerMustNotWrite"}, headers={"X-CSRF-Token": csrf, "Origin": public_url})
        assert response.status == 403, "The real server did not refuse the viewer's write"
        assert "permission_denied" in response.text() or "当前角色为只读" in response.text(), "A transport or CSRF refusal cannot qualify role enforcement"
        assert j.tag("TripFinal")["id"] == original["id"]
        viewer.screenshot(path=j.evidence / "web-reference-viewer-saved-view.png", full_page=True)
    j.native.restart()
    j.native_open("标签")
    j.native.reveal_any("TripFinal")
    j.native.capture("reference-member-edit-read-by-owner")


def appearances(j):
    page, native = j.page, j.native
    for theme in ("paper", "midnight"):
        page.set_viewport_size({"width": 1280, "height": 960})
        j.goto("/web/tags")
        page.locator("#appearance > summary").click()
        page.locator(f'#appearance [data-theme-mode="{theme}"]').click()
        page.wait_for_function("theme => document.documentElement.dataset.theme === theme", arg=theme)
        page.locator("#appearance > summary").click()
        for width in (1280, 390):
            page.set_viewport_size({"width": width, "height": 960})
            for path in PAGES:
                j.goto(f"/web/{path}")
                assert page.locator("html").get_attribute("data-theme") == theme
                j.capture(f"{path}-{width}-{theme}")
        native.plan_home()
        native.click("打开账户与设置")
        native.click("外观与主题")
        native.click("浅色纸面 · 深绿点缀" if theme == "paper" else "柔和深色 · 浅绿点缀")
        for label, value, name in (("标签", "TripFinal", "tags"), ("商家", "RefPay", "merchants"),
                                    ("自动规则", "RefShop", "rules"), ("分类", "Library", "categories")):
            j.native_open(label)
            native.reveal_any(value, max_scrolls=16)
            native.capture(f"reference-{name}-{theme}")


def identities(j):
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import Ledger

    native = j.native
    native.plan_home()
    native.click("打开账户与设置")
    native.click("账本")
    native.reveal_any("账本名称")
    native.fill("LibraryOther", label="账本名称")
    native.click("新建账本", bottom=True)
    native.reveal_any("已新建账本")
    native.click_within("LibraryOther", "切换")
    native.reveal_any("已切换到「LibraryOther」")
    for label, forbidden in (("标签", "TripFinal"), ("商家", "RefShop"), ("自动规则", "RefShop")):
        j.native_open(label)
        assert not native.has(forbidden), "The new ledger exposed the previous ledger's reference data"
        native.capture(f"reference-other-ledger-{label}")
    with SessionLocal() as db:
        other = db.scalar(select(Ledger).where(Ledger.name == "LibraryOther"))
        assert other is not None and other.ledger_id != j.fixture.ledger_id
        other_facts = facts(other.ledger_id)
        assert all(not value for value in other_facts.values()), "Switching copied reference or financial facts into another ledger"
    native.plan_home()
    native.click("打开账户与设置")
    native.click("账本")
    native.click_within(j.fixture.ledger_name, "切换")
    native.reveal_any(f"已切换到「{j.fixture.ledger_name}」")
    native.plan_home()
    native.click("打开账户与设置")
    native.click("安全与隐私")
    native.click("退出账本")
    native.click("确定退出")
    native.bind(_member_code(j.fixture.ledger_id, "viewer"), j.port)
    j.native_open("标签")
    native.reveal_any("TripFinal")
    wait_for(lambda: native.has("只读"), "The rebound viewer retained owner editing rights")
    assert not native.has("标签操作")
    native.capture("reference-original-ledger-viewer-binding")


def qualify_consumers(j):
    roles(j)
    appearances(j)
    identities(j)
