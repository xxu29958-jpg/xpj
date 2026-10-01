"""Use local appearance settings while reading the actual five-domain product."""

import hashlib

from PIL import Image, ImageDraw

from scripts.insights_journey import InsightsJourney
from scripts.planning_appearance_journey_native import native_appearance
from scripts.planning_journey_android import wait_for


def background_fixture(path):
    # Synthetic black/white blocks stress arbitrary-image readability. This is
    # picker input, never a replacement product screen or a user attachment.
    image = Image.new("RGB", (1200, 1800), "white")
    draw = ImageDraw.Draw(image)
    for y in range(0, 1800, 150):
        for x in range(0, 1200, 150):
            if (x // 150 + y // 150) % 2 == 0:
                draw.rectangle((x, y, x + 149, y + 149), fill="black")
    image.save(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AppearanceJourney:
    def __init__(self, page, native, fixture, evidence, base_url):
        self.context = InsightsJourney(page, native, fixture, evidence, base_url)
        self.page, self.native, self.evidence = page, native, evidence

    def menu(self):
        root = self.page.locator("#ledger-switcher" if self.page.viewport_size["width"] < 768 else "#appearance")
        if root.get_attribute("open") is None:
            root.locator(":scope > summary").click()
        return root

    def import_image(self, path):
        with self.page.expect_file_chooser() as chooser:
            self.menu().locator("[data-background-import]").click()
        chooser.value.set_files(str(path))
        self.page.locator("dialog.bg-editor").wait_for(state="visible")

    def web_appearance(self, path):
        page = self.page
        self.context.goto("/web/overview")
        self.import_image(path)
        page.locator('[data-bg-act="zoom-in"]').click()
        page.keyboard.press("ArrowRight")
        assert page.evaluate("window.TicketboxBackground.applied()") is None
        page.keyboard.press("Escape")
        page.locator("dialog.bg-editor").wait_for(state="hidden")
        assert page.evaluate("window.TicketboxBackground.applied()") is None
        self.import_image(path)
        page.locator('[data-bg-act="zoom-in"]').click()
        page.keyboard.press("ArrowRight")
        page.locator('[data-bg-act="apply"]').click()
        page.locator("dialog.bg-editor").wait_for(state="hidden")
        transform = page.evaluate("window.TicketboxBackground.applied().transform")
        assert transform["scale"] > 1 and transform["offsetX"] > 0
        for width in (1280, 390):
            page.set_viewport_size({"width": width, "height": 960})
            for theme in ("paper", "midnight"):
                self.menu().locator(f'[data-theme-mode="{theme}"]').click()
                page.keyboard.press("Escape")
                for domain in ("pending", "confirmed", "debts", "budgets", "overview"):
                    self.context.goto("/web/" + domain)
                    wait_for(lambda: page.evaluate("() => window.TicketboxBackground.applied() !== null"),
                        "The saved Web background did not load")
                    assert page.evaluate("window.TicketboxBackground.applied().transform") == transform
                    assert page.locator("html").get_attribute("data-theme") == theme
                    self.context.capture(f"appearance-{domain}-{width}-{theme}")
        self.menu().locator("[data-background-edit]").click()
        page.keyboard.press("ArrowLeft")
        page.keyboard.press("Escape")
        page.locator("dialog.bg-editor").wait_for(state="hidden")
        page.reload()
        wait_for(lambda: page.evaluate("() => window.TicketboxBackground.applied() !== null"),
            "Reload did not retain the applied background")
        assert page.evaluate("window.TicketboxBackground.applied().transform") == transform
        self.menu().locator('[data-theme-mode="system"]').click()
        page.keyboard.press("Escape")
        for scheme, theme in (("dark", "midnight"), ("light", "paper")):
            page.emulate_media(color_scheme=scheme)
            wait_for(lambda theme=theme: page.locator("html").get_attribute("data-theme") == theme,
                "The real Web consumer did not follow the system theme")
        self.menu().locator("[data-background-clear]").click()
        wait_for(lambda: page.evaluate("() => window.TicketboxBackground.applied() === null"),
            "The actual background owner did not clear its saved image")
        page.reload()
        wait_for(lambda: page.locator("html").get_attribute("data-user-bg") is None,
            "The cleared Web background returned after reload")
        self.context.capture("appearance-restored-theme")
        return transform

    def run(self):
        self.context.prepare()
        before = self.context.facts()
        image = self.evidence / "synthetic-background.png"
        image_digest = background_fixture(image)
        transform = self.web_appearance(image)
        native = native_appearance(self.context, image, image_digest)
        assert self.context.facts() == before, "Appearance changed the confirmed financial facts"
        return {"verified_leg": "Actual Web and native local background import, unpublished draft cancellation, "
                "apply, built-in selection, five-domain reads in both themes and all three immersion modes, "
                "original composition after restart, named motion controls, system theme and restore default; "
                "confirmed facts unchanged",
            "financial_facts_unchanged": True, "expense_count": len(before["expenses"]),
            "synthetic_image_sha256": image_digest, "web_transform": transform, "native": native,
            "limits": "Appearance qualification only. Inbox, obligations and plans use their real empty states; "
                "ledger and insights read three actual confirmed expenses. Screenshot readability needs review. "
                "Image decode and persistence failures retain their existing focused component gates."}
