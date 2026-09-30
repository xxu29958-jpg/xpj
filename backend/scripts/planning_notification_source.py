"""Build the disposable payment source APKs for the existing cloud journey.

The whitelisted package names exist only on a fresh isolated emulator. Each APK
is marked testOnly, has no network permission, and refuses to post off-emulator.
The real Android notification manager delivers to the installed Ticketbox NLS.
"""

from __future__ import annotations

import os
import subprocess
import time
import zipfile
from pathlib import Path

from scripts.planning_journey_android import wait_for

SOURCES = ("com.eg.android.AlipayGphone", "com.jingdong.app.mall", "ticketbox.journey.unlisted")
RECEIVER = "ticketbox.journey.PaymentSampleReceiver"


def notification_control(root, label: str):
    """A collapsed group's preview is not its individual notification action."""
    matches = [node for node in root.iter("node") if label in node.attrib.get("text", "")]
    assert len(matches) == 1, "The original system reminder must be distinguishable"
    parents = {child: parent for parent in root.iter("node") for child in parent}
    node, rows = matches[0], []
    while node in parents:
        node = parents[node]
        if node.attrib.get("resource-id") == "com.android.systemui:id/expandableNotificationRow":
            rows.append(node)
    assert rows, "The reminder is not inside an actual Android notification row"
    if rows[0].attrib.get("clickable") == "true":
        return "open", matches[0]
    groups = [row for row in rows[1:] if row.attrib.get("clickable") == "true"]
    assert groups, "The collapsed reminder has no containing notification group"
    controls = [node for node in groups[0].iter("node") if
        node.attrib.get("resource-id") == "android:id/expand_button" and node.attrib.get("content-desc") == "Expand"]
    assert len(controls) == 1, "The containing notification group has no unique expand control"
    return "expand", controls[0]


class SystemPaymentSources:
    def __init__(self, native, output: Path):
        self.native = native
        for package, apk in build_sources(output).items():
            assert not native.adb("shell", "pm", "list", "packages", package).strip(), "The disposable source package already exists"
            native.adb("install", "-t", str(apk))
            native.adb("shell", "pm", "grant", package, "android.permission.POST_NOTIFICATIONS")

    def post(self, source: str, sample: int):
        assert source in SOURCES
        output = self.native.adb("shell", "am", "broadcast", "-n", f"{source}/{RECEIVER}", "--ei", "sample", str(sample))
        assert f"Broadcast completed: result={100 + sample}" in output, "The isolated receiver did not acknowledge its actual Android notification operation"

    def authorize_listener(self):
        native = self.native
        native.reveal_any("打开系统授权")
        native.click("打开系统授权")
        native.click("小票夹")

        def actual_switch():
            return [node for node in native.tree().iter("node") if
                node.attrib.get("package") == "com.android.settings" and
                node.attrib.get("checkable") == "true" and "Switch" in node.attrib.get("class", "")]

        switches = wait_for(actual_switch, "Android did not show the notification-access control")
        assert len(switches) == 1 and switches[0].attrib.get("checked") == "false"
        native.tap(switches[0])
        native.click("Allow")
        component = "com.ticketbox/com.ticketbox.notification.TicketboxNotificationListenerService"
        wait_for(lambda: component in native.adb("shell", "settings", "get", "secure", "enabled_notification_listeners"),
            "The actual Android notification access was not granted")
        native.capture("notification-system-access-granted")
        native.back()
        native.back()
        native.reveal_any("本机解析支付通知")

    def capture_payments(self, facts):
        native = self.native
        self.authorize_listener()
        # Access alone must not enable capture. A later accepted delivery provides
        # a processing boundary for checking these earlier ignored samples.
        self.post(SOURCES[0], 3)
        time.sleep(2)
        native.set_switch("本机解析支付通知", True)
        self.post(SOURCES[2], 3)
        self.post(SOURCES[0], 0)
        wait_for(lambda: len(facts()["captures"]) == 1, "The enabled real listener did not accept the whitelisted repayment")
        assert facts()["expenses"] == 0, "Default-off or unlisted notifications created an Expense"
        native.set_switch("本机解析支付通知", False)
        self.post(SOURCES[0], 3)
        time.sleep(2)
        native.set_switch("本机解析支付通知", True)
        self.post(SOURCES[1], 1)
        wait_for(lambda: len(facts()["captures"]) == 2, "Capture did not resume after the application switch was enabled")
        assert facts()["expenses"] == 0, "The disabled application switch still captured a payment"
        self.post(SOURCES[0], 2)
        wait_for(lambda: facts()["expenses"] == 1, "The real listener did not classify the consumer payment as an Expense draft")
        assert facts()["payments"] == [], "System capture must not create repayment facts"
        for source in SOURCES:
            self.post(source, 4)
        native.capture("notification-system-capture-complete")


def build_sources(output: Path) -> dict[str, Path]:
    sdk = Path(os.environ["ANDROID_HOME"])
    java = Path(os.environ["JAVA_HOME"]) / "bin"
    suffix = ".exe" if os.name == "nt" else ""
    script_suffix = ".bat" if os.name == "nt" else ""
    build = sdk / "build-tools" / "36.0.0"
    android = sdk / "platforms" / "android-36" / "android.jar"
    output.mkdir(parents=True, exist_ok=True)

    def run(*args):
        result = subprocess.run([str(arg) for arg in args], capture_output=True, text=True, check=False)
        if result.returncode:
            raise RuntimeError(f"Isolated payment fixture build failed: {Path(args[0]).name}\n{result.stderr[-2000:]}")

    classes, dex = output / "classes", output / "dex"
    classes.mkdir(exist_ok=True)
    dex.mkdir(exist_ok=True)
    source = Path(__file__).with_name("notification_payment_fixture") / "PaymentSampleReceiver.java"
    run(java / ("javac" + suffix), "-encoding", "UTF-8", "-source", "8", "-target", "8", "-classpath", android, "-d", classes, source)
    run(build / ("d8" + script_suffix), "--lib", android, "--min-api", "28", "--output", dex,
        classes / "ticketbox" / "journey" / "PaymentSampleReceiver.class")
    key = output / "fixture.p12"
    run(java / ("keytool" + suffix), "-genkeypair", "-keystore", key, "-storepass", "isolated-fixture",
        "-alias", "fixture", "-dname", "CN=Ticketbox Cloud Fixture", "-keyalg", "RSA", "-keysize", "2048", "-validity", "2")
    result = {}
    for package in SOURCES:
        folder = output / package
        folder.mkdir(exist_ok=True)
        manifest = folder / "AndroidManifest.xml"
        manifest.write_text(f'''<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="{package}">
          <uses-permission android:name="android.permission.POST_NOTIFICATIONS"/>
          <application android:label="Ticketbox Cloud Payment Fixture" android:testOnly="true" android:allowBackup="false">
            <receiver android:name="{RECEIVER}" android:exported="true" android:permission="android.permission.DUMP"/>
          </application>
        </manifest>''', encoding="utf-8")
        unsigned, aligned, apk = folder / "unsigned.apk", folder / "aligned.apk", folder / "source.apk"
        run(build / ("aapt2" + suffix), "link", "-I", android, "--manifest", manifest,
            "--min-sdk-version", "28", "--target-sdk-version", "36", "-o", unsigned)
        with zipfile.ZipFile(unsigned, "a") as archive:
            archive.write(dex / "classes.dex", "classes.dex")
        run(build / ("zipalign" + suffix), "-p", "4", unsigned, aligned)
        run(build / ("apksigner" + script_suffix), "sign", "--ks", key, "--ks-pass", "pass:isolated-fixture", "--out", apk, aligned)
        run(build / ("apksigner" + script_suffix), "verify", apk)
        result[package] = apk
    return result
