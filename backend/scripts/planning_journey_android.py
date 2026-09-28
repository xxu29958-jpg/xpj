"""UI-tree driven actions for the isolated income/goal consumer journey."""

from __future__ import annotations

import re
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path


def wait_for(condition, message: str, timeout: float = 60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = condition()
        if result:
            return result
        time.sleep(0.3)
    raise AssertionError(message)


class PlanningAndroid:
    def __init__(self, serial: str, evidence: Path):
        if not serial.startswith("emulator-"):
            raise RuntimeError("This journey only runs on its isolated emulator")
        self.serial = serial
        self.evidence = evidence
        self.bound = False
        self.pairing_code = ""
        self.tree_attempt = 0
        if self.adb("shell", "getprop", "ro.kernel.qemu").strip() != "1":
            raise RuntimeError("The selected target is not an emulator")

    def adb(self, *args: str, binary: bool = False):
        result = subprocess.run(["adb", "-s", self.serial, *args], capture_output=True, timeout=30, check=False)
        if result.returncode:
            # Input arguments can contain the temporary pairing code.
            raise RuntimeError("An isolated-emulator command failed")
        return result.stdout if binary else result.stdout.decode("utf-8", errors="replace")

    def tree(self):
        def read_tree():
            self.tree_attempt += 1
            path = f"/sdcard/planning-journey-{self.tree_attempt}.xml"
            dump = self.adb("shell", "uiautomator", "dump", path)
            raw = self.adb("exec-out", "cat", path)
            try:
                return [ET.fromstring(raw)]
            except ET.ParseError:
                diagnostic = dump + "\n" + raw
                if self.pairing_code:
                    diagnostic = diagnostic.replace(self.pairing_code, "[temporary pairing code removed]")
                (self.evidence / "android-tree-diagnostic.txt").write_text(diagnostic, encoding="utf-8")
                return None
        return wait_for(read_tree, "The emulator did not provide a valid UI hierarchy", 45)[0]

    @staticmethod
    def bounds(node):
        values = [int(part) for part in re.findall(r"\d+", node.attrib["bounds"])]
        if len(values) != 4 or values[2] <= values[0] or values[3] <= values[1]:
            raise AssertionError("The actual UI node has no touchable bounds")
        return values

    def tap(self, node):
        left, top, right, bottom = self.bounds(node)
        self.adb("shell", "input", "tap", str((left + right) // 2), str((top + bottom) // 2))

    def has(self, text: str):
        return any(text in node.attrib.get("text", "") or text in node.attrib.get("content-desc", "")
                   for node in self.tree().iter("node"))

    def click(self, text: str, *, bottom: bool = False):
        scrolls = 0
        def locate():
            nonlocal scrolls
            nodes = list(self.tree().iter("node"))
            matches = [node for node in nodes if text in (node.attrib.get("text"), node.attrib.get("content-desc"))]
            scrollable = [node for node in nodes if node.attrib.get("scrollable") == "true"]
            if not matches and scrollable and scrolls < 4:
                left, top, right, end = self.bounds(max(scrollable, key=lambda node: self.bounds(node)[3] - self.bounds(node)[1]))
                center = str((left + right) // 2)
                self.adb("shell", "input", "swipe", center, str(top + (end - top) * 4 // 5),
                    center, str(top + (end - top) // 4), "350")
                scrolls += 1
            return matches
        matches = wait_for(locate, f"Native action is not reachable: {text}")
        if bottom:
            self.tap(max(matches, key=lambda node: self.bounds(node)[3]))
        else:
            if len(matches) != 1:
                raise AssertionError(f"Native action is ambiguous: {text}")
            self.tap(matches[0])

    def fill(self, value: str, *, previous: str | None = None):
        if not re.fullmatch(r"[A-Za-z0-9.:/_-]+", value):
            raise ValueError("This journey types only its numeric or ASCII inputs")
        def locate():
            fields = [node for node in self.tree().iter("node") if node.attrib.get("class") == "android.widget.EditText"]
            return [node for node in fields if re.fullmatch(previous, node.attrib.get("text", ""))] if previous is not None else fields
        fields = wait_for(locate, "The native input did not finish loading")
        if len(fields) != 1:
            raise AssertionError("The native input cannot be identified from its actual value")
        self.tap(fields[0])
        self.adb("shell", "input", "keycombination", "113", "29")
        self.adb("shell", "input", "text", value)
        self.adb("shell", "input", "keyevent", "4")

    def reveal_any(self, *texts: str):
        for attempt in range(8):
            nodes = list(self.tree().iter("node"))
            if any(text in node.attrib.get("text", "") for node in nodes for text in texts):
                return
            scrollable = [node for node in nodes if node.attrib.get("scrollable") == "true"]
            handles = [node for node in nodes if node.attrib.get("content-desc") == "Drag handle"]
            if scrollable:
                left, top, right, bottom = self.bounds(max(scrollable, key=lambda node: self.bounds(node)[3] - self.bounds(node)[1]))
                x, start, end = (left + right) // 2, top + (bottom - top) * 4 // 5, top + (bottom - top) // 5
            elif handles and attempt == 0:
                left, top, right, bottom = self.bounds(handles[0])
                window_bottom = self.bounds(nodes[0])[3]
                x, start, end = (left + right) // 2, (top + bottom) // 2, window_bottom // 8
            else:
                time.sleep(0.3)
                continue
            self.adb("shell", "input", "swipe", str(x), str(start), str(x), str(end), "450")
        raise AssertionError(f"The actual native content is not reachable after scrolling: {texts}")

    def bind(self, code: str, port: int):
        self.adb("reverse", f"tcp:{port}", f"tcp:{port}")
        self.adb("shell", "am", "start", "-n", "com.ticketbox/.MainActivity")
        wait_for(lambda: self.has("绑定账本"), "The native binding screen did not open")
        self.pairing_code = code
        self.fill(code)
        self.click("绑定账本")
        wait_for(lambda: self.has("计划"), "The native application did not reach the bound product")
        self.bound = True

    def open_income(self):
        self.plan_home()
        self.click("收入计划")
        self.reveal_any("联动工资")

    def open_goals(self):
        self.plan_home()
        self.click("消费目标")
        self.reveal_any("联动消费提醒")

    def open_goal(self):
        self.open_goals()
        self.click("联动消费提醒")
        wait_for(lambda: self.has("编辑目标"), "The native goal detail did not open")

    def connection(self, port: int, *, online: bool):
        if online:
            self.adb("reverse", f"tcp:{port}", f"tcp:{port}")
        else:
            self.adb("reverse", "--remove", f"tcp:{port}")

    def restart(self):
        self.adb("shell", "am", "force-stop", "com.ticketbox")
        self.adb("shell", "am", "start", "-n", "com.ticketbox/.MainActivity")
        wait_for(lambda: self.has("计划"), "The saved native identity did not reopen")

    def recycle_bin(self):
        self.plan_home()
        self.click("流水", bottom=True)
        self.click("账本工具")
        self.click("资料库")
        self.click("回收站")

    def click_within(self, anchor: str, action: str):
        def locate():
            root = self.tree()
            candidates = []
            for parent in root.iter("node"):
                descendants = list(parent.iter("node"))
                if not any(anchor == node.attrib.get("text") for node in descendants):
                    continue
                actions = [node for node in descendants if action in (node.attrib.get("text"), node.attrib.get("content-desc"))]
                if len(actions) == 1:
                    candidates.append((len(descendants), actions[0]))
            return min(candidates, key=lambda candidate: candidate[0])[1] if candidates else None
        node = wait_for(lambda: (found := locate()) is not None and [found], f"The action {action} is not within {anchor}")[0]
        self.tap(node)

    def plan_home(self):
        for _ in range(5):
            if any(node.attrib.get("text") == "计划" for node in self.tree().iter("node")):
                self.click("计划", bottom=True)
                return
            self.back()
        raise AssertionError("The real navigation did not return to the planning entry")

    def capture(self, name: str, redact: str | None = None):
        if self.bound or not self.pairing_code:
            (self.evidence / f"android-{name}.png").write_bytes(self.adb("exec-out", "screencap", "-p", binary=True))
        tree = ET.tostring(self.tree(), encoding="unicode")
        secret = redact or self.pairing_code
        if secret:
            tree = tree.replace(secret, "[temporary pairing code removed]")
        (self.evidence / f"android-{name}.xml").write_text(tree, encoding="utf-8")

    def back(self):
        self.adb("shell", "input", "keyevent", "4")
