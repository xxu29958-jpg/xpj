"""Temporary unmerged execution of two existing Room risk checks."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

root = Path("t3-family-evidence")
root.mkdir(exist_ok=True)
source = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
assert source == os.environ["GITHUB_SHA"]
assert subprocess.check_output(["adb", "-s", "emulator-5554", "shell", "getprop", "ro.kernel.qemu"], text=True).strip() == "1"
apks = [Path("android/app/build/outputs/apk/gray/debug/app-gray-debug.apk"),
        Path("android/app/build/outputs/apk/androidTest/gray/debug/app-gray-debug-androidTest.apk")]
identity = {"source_sha": source, "run_id": os.environ["GITHUB_RUN_ID"],
            "apks": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in apks}}
(root / "identity.json").write_text(json.dumps(identity, indent=2), encoding="utf-8")
for apk in apks:
    subprocess.run(["adb", "-s", "emulator-5554", "install", "-r", str(apk)], check=True)
classes = ["com.ticketbox.ui.navigation.FamilyInvitationNavigationTest#chosenInviteAndUnknownRevokeKeepTheirOriginalScope"]
result = subprocess.run(["adb", "-s", "emulator-5554", "shell", "am", "instrument", "-w", "-e", "class", ",".join(classes),
                         "com.ticketbox.test/androidx.test.runner.AndroidJUnitRunner"], capture_output=True, text=True, timeout=180)
(root / "instrumentation.txt").write_text(result.stdout + result.stderr, encoding="utf-8")
print(result.stdout, result.stderr)
subprocess.run(["adb", "-s", "emulator-5554", "pull", "/sdcard/Android/data/com.ticketbox/files/consumer-art-previews", str(root / "screenshots")], check=False)
assert result.returncode == 0 and "OK (1 test)" in result.stdout, "The existing invitation consumer did not pass"
