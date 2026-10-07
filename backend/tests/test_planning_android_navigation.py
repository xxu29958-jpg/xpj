"""Keep UI navigation bounded when asynchronous content changes the viewport."""

import xml.etree.ElementTree as ET

import pytest

from scripts.planning_journey_android import PlanningAndroid


class ScrollableNative(PlanningAndroid):
    def __init__(self, position, target, length=7):
        self.position = position
        self.target = target
        self.length = length
        self.swipes = []
        self.captures = []
        self.tree_attempt = 0

    def tree(self):
        self.tree_attempt += 1
        root = ET.Element("hierarchy")
        viewport = ET.SubElement(root, "node", scrollable="true", bounds="[0,0][400,800]")
        text = "remaining action" if self.position == self.target else f"history {self.position}"
        ET.SubElement(viewport, "node", text=text, bounds="[0,100][400,200]")
        return root

    def adb(self, *args, **_kwargs):
        assert args[:3] == ("shell", "input", "swipe")
        direction = 1 if int(args[4]) > int(args[6]) else -1
        self.swipes.append(direction)
        self.position = min(self.length - 1, max(0, self.position + direction))

    def capture(self, name, **_kwargs):
        self.captures.append(name)


def test_reflow_above_current_viewport_does_not_hide_a_reachable_action():
    native = ScrollableNative(position=4, target=2)

    native.reveal_any("remaining action")

    assert native.position == 2
    assert -1 in native.swipes
    assert native.captures, "Keep actual UI evidence when recovering in the other direction"


def test_inspects_the_viewport_reached_by_the_last_permitted_swipe():
    native = ScrollableNative(position=0, target=2)

    native.reveal_any("remaining action", max_scrolls=2)

    assert native.position == 2
    assert native.swipes == [1, 1]


def test_missing_action_still_fails_after_a_bounded_search_in_both_directions():
    native = ScrollableNative(position=2, target=None)

    with pytest.raises(AssertionError, match="not reachable"):
        native.reveal_any("remaining action", max_scrolls=3)

    assert len(native.swipes) <= 6
    assert not native.captures


def test_domain_return_uses_navigation_instead_of_a_same_named_recycle_filter():
    class Native(PlanningAndroid):
        def __init__(self):
            self.page = "recycle"
            self.visited = []

        def tree(self):
            root = ET.Element("hierarchy")
            labels = {"recycle": ["回收站", "计划"], "library": ["资料库"],
                      "ledger": ["流水", "流水", "计划"], "budget": ["预算"],
                      "plans": ["计划", "计划"]}[self.page]
            for text in labels:
                ET.SubElement(root, "node", text=text)
            if self.page in {"ledger", "plans"}:
                ET.SubElement(root, "node", attrib={"content-desc": "打开账户与设置"})
            return root

        def click(self, label, **_kwargs):
            assert self.page == "ledger", "The recycle filter is not domain navigation"
            assert label == "计划"
            self.page = "budget"  # The target domain restores its existing secondary stack.
            self.visited.append(self.page)

        def back(self):
            self.page = {"recycle": "library", "library": "ledger", "budget": "plans"}[self.page]
            self.visited.append(self.page)

    native = Native()
    native.domain_home("计划")
    assert native.visited == ["library", "ledger", "budget", "plans"]
