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
        if self.adb("shell", "getprop", "ro.kernel.qemu").strip() != "1":
            raise RuntimeError("The selected target is not an emulator")

    def adb(self, *args: str, binary: bool = False):
        result = subprocess.run(["adb", "-s", self.serial, *args], capture_output=True, timeout=30, check=False)
        if result.returncode:
            # Input arguments can contain the temporary pairing code.
            raise RuntimeError("An isolated-emulator command failed")
        return result.stdout if binary else result.stdout.decode("utf-8", errors="replace")

    def tree(self):
        self.adb("shell", "uiautomator", "dump", "/sdcard/planning-journey.xml")
        return ET.fromstring(self.adb("exec-out", "cat", "/sdcard/planning-journey.xml"))

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
        fields = [node for node in self.tree().iter("node") if node.attrib.get("class") == "android.widget.EditText"]
        if previous is not None:
            fields = [node for node in fields if re.fullmatch(previous, node.attrib.get("text", ""))]
        if len(fields) != 1:
            raise AssertionError("The native input cannot be identified from its actual value")
        self.tap(fields[0])
        self.adb("shell", "input", "keycombination", "113", "29")
        self.adb("shell", "input", "text", value)
        self.adb("shell", "input", "keyevent", "4")

    def bind(self, code: str, port: int):
        self.adb("reverse", f"tcp:{port}", f"tcp:{port}")
        self.adb("shell", "am", "start", "-n", "com.ticketbox/.MainActivity")
        wait_for(lambda: self.has("绑定账本"), "The native binding screen did not open")
        self.fill(code)
        self.click("绑定账本")
        wait_for(lambda: self.has("计划"), "The native application did not reach the bound product")
        self.bound = True

    def open_income(self):
        self.plan_home()
        self.click("收入计划")
        wait_for(lambda: self.has("联动工资"), "The Web-created income did not reach the actual native consumer")

    def plan_home(self):
        for _ in range(5):
            if any(node.attrib.get("text") == "计划" for node in self.tree().iter("node")):
                self.click("计划", bottom=True)
                return
            self.back()
        raise AssertionError("The real navigation did not return to the planning entry")

    def capture(self, name: str, redact: str | None = None):
        tree = ET.tostring(self.tree(), encoding="unicode")
        if redact:
            tree = tree.replace(redact, "[temporary pairing code removed]")
        (self.evidence / f"android-{name}.xml").write_text(tree, encoding="utf-8")
        if not self.bound:
            return
        (self.evidence / f"android-{name}.png").write_bytes(self.adb("exec-out", "screencap", "-p", binary=True))

    def back(self):
        self.adb("shell", "input", "keyevent", "4")
