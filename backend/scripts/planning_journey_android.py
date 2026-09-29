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
                    diagnostic = (diagnostic.replace(self.pairing_code, "[temporary pairing code removed]")
                        if self.bound else "The unparsed binding hierarchy was withheld")
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
            matches = [node for node in nodes if node.attrib.get("enabled") != "false" and
                       text in (node.attrib.get("text"), node.attrib.get("content-desc"))]
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

    def fill(self, value: str, *, previous: str | None = None, label: str | None = None):
        if not re.fullmatch(r"[A-Za-z0-9.:/_-]+", value):
            raise ValueError("This journey types only its numeric or ASCII inputs")
        def locate():
            root = self.tree()
            fields = self.labeled_fields(root, label) if label else [
                node for node in root.iter("node") if node.attrib.get("class") == "android.widget.EditText"]
            fields = [node for node in fields if node.attrib.get("enabled") != "false"]
            return [node for node in fields if re.fullmatch(previous, node.attrib.get("text", ""))] if previous is not None else fields
        fields = wait_for(locate, "The native input did not finish loading")
        if len(fields) != 1:
            raise AssertionError("The native input cannot be identified from its actual value")
        self.tap(fields[0])
        def focused_value():
            inputs = [node for node in self.tree().iter("node") if
                node.attrib.get("class") == "android.widget.EditText" and node.attrib.get("focused") == "true"]
            return inputs[0].attrib.get("text", "") if len(inputs) == 1 else None
        original = wait_for(lambda: (text := focused_value()) is not None and [text],
            "The actual native field did not receive focus")[0]
        self.adb("shell", "input", "keyevent", "123")
        for end in range(len(original) - 1, -1, -1):
            self.adb("shell", "input", "keyevent", "67")
            wait_for(lambda end=end: focused_value() == original[:end], "The native input did not remove the selected character")
        for end, character in enumerate(value, start=1):
            self.adb("shell", "input", "text", character)
            wait_for(lambda end=end: focused_value() == value[:end], "The native input did not retain the typed text")
        self.adb("shell", "input", "keyevent", "4")

    def click_counted_tab(self, label: str):
        def locate():
            return [node for node in self.tree().iter("node")
                    if re.fullmatch(re.escape(label) + r" \d+", node.attrib.get("text", ""))]
        nodes = wait_for(locate, f"The actual counted tab is not visible: {label}")
        assert len(nodes) == 1, "The actual counted tab is ambiguous"
        self.tap(nodes[0])

    @staticmethod
    def labeled_fields(root, label):
        candidates = []
        for parent in root.iter("node"):
            nodes = list(parent.iter("node"))
            fields = [node for node in nodes if node.attrib.get("class") == "android.widget.EditText"]
            if len(fields) == 1 and any(node.attrib.get("text") == label for node in nodes):
                candidates.append((len(nodes), fields))
        return min(candidates, key=lambda item: item[0])[1] if candidates else []

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
        root = self.tree()
        if self.pairing_code and not self.bound:
            for node in root.iter("node"):
                if node.attrib.get("class") == "android.widget.EditText":
                    node.attrib["text"] = "[temporary binding input removed]"
        tree = ET.tostring(root, encoding="unicode")
        secret = redact or self.pairing_code
        if secret:
            tree = tree.replace(secret, "[temporary pairing code removed]")
        (self.evidence / f"android-{name}.xml").write_text(tree, encoding="utf-8")

    def back(self):
        self.adb("shell", "input", "keyevent", "4")
