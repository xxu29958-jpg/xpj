"""Operate the app's photo picker/editor, then read its persisted local result."""

import hashlib
import re
import xml.etree.ElementTree as ET

from scripts.planning_journey_android import wait_for


def open_appearance(native):
    native.plan_home()
    native.click("打开账户与设置")
    native.click("外观与主题")


def saved_background(native):
    paths = native.adb("exec-out", "run-as", "com.ticketbox", "find", "files", "-name",
        "ticketbox_background_settings.preferences_pb").splitlines()
    assert len(paths) <= 1, "The app has more than one background settings file"
    raw = native.adb("exec-out", "run-as", "com.ticketbox", "cat", paths[0], binary=True) if paths else b""
    return hashlib.sha256(raw).hexdigest()


def private_images(native):
    paths = native.adb("exec-out", "run-as", "com.ticketbox", "find", "files", "-path",
        "files/backgrounds/*.image", "-type", "f").splitlines()
    return {path: hashlib.sha256(native.adb("exec-out", "run-as", "com.ticketbox", "cat", path,
                binary=True)).hexdigest() for path in paths}


def theme_mode(native):
    # Never emit the settings file: unrelated entries include binding secrets.
    root = ET.fromstring(native.adb("exec-out", "run-as", "com.ticketbox", "cat",
        "shared_prefs/ticketbox_settings.xml"))
    return next((node.text for node in root if node.attrib.get("name") == "app_theme_mode"), None)


def prepare_photo(native, path):
    device_path = "/sdcard/Pictures/appearance-background.png"
    native.adb("push", str(path), device_path)
    native.adb("shell", "am", "broadcast", "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
        "-d", "file://" + device_path)

    def admitted():
        rows = native.adb("shell", "content", "query", "--uri", "content://media/external/images/media",
            "--projection", "_id:_display_name")
        images = [row for row in rows.splitlines() if re.search(r"_id=\d+", row)]
        assert len(images) <= 1, "The isolated picker must contain only its known fixture"
        return len(images) == 1 and "_display_name=appearance-background.png" in images[0]

    wait_for(admitted, "The isolated photo did not enter the actual media provider")


def pick_photo(native):
    native.reveal_any("从相册选择")
    native.click("从相册选择")

    def photo():
        # Android 16 Photo Picker exposes each media cell with its localized
        # 'Photo taken on ...' description; this cloud emulator uses English.
        nodes = [node for node in native.tree().iter("node")
            if node.attrib.get("content-desc", "").startswith("Photo taken on ")]
        assert len(nodes) <= 1, "The actual picker exposes an ambiguous image"
        return nodes

    nodes = wait_for(photo, "The actual Photo Picker did not expose the known image")
    native.capture("appearance-photo-picker")
    native.tap(nodes[0])
    wait_for(lambda: native.has("应用背景"), "The actual selected image did not open the editor")


def read_domains(native, images):
    for theme, label in (("paper", "温润米白 + 茶铜"), ("midnight", "深色玻璃 + 暖金")):
        open_appearance(native)
        native.click(label)
        wait_for(lambda theme=theme: theme_mode(native) == theme, "The native theme choice was not persisted")
        for mode, choice, description in (("atmosphere", "氛围", "背景更明显，适合首页和统计"),
                ("balanced", "平衡", "默认推荐，兼顾好看和清晰"), ("focus", "专注", "弱化背景，适合长时间记账")):
            open_appearance(native)
            native.reveal_any("减少动效")
            previous = saved_background(native)
            native.click(choice, bottom=True)
            wait_for(lambda description=description: native.has(description), "The immersion choice did not reach the UI")
            wait_for(lambda previous=previous: saved_background(native) != previous, "The immersion choice was not persisted")
            selected = saved_background(native)
            for domain, slug in (("收件", "inbox"), ("流水", "ledger"), ("往来", "obligations"),
                    ("计划", "plans"), ("洞察", "insights")):
                native.domain_home(domain)
                if domain == "流水":
                    native.reveal_any("TaggedMeal")
                native.capture(f"appearance-{slug}-{theme}-{mode}")
            assert saved_background(native) == selected and private_images(native) == images
        native.domain_home("流水")
        native.reveal_any("TaggedMeal")
        native.click("TaggedMeal")
        native.click("更正这笔账单")
        native.capture(f"appearance-correction-{theme}")
        # No edit/submit: preserve all original financial facts and intentions.
        native.back()
    return saved_background(native)


def native_appearance(j, path, image_digest):
    native = j.native
    prepare_photo(native, path)
    open_appearance(native)
    native.click("背景图库")
    native.click("茶雾")
    native.click("应用背景")
    wait_for(lambda: not native.has("应用背景"), "The built-in background did not publish")
    native.reveal_any("内置背景", toward_start=True)
    native.capture("appearance-builtin-applied")
    original = saved_background(native)
    pick_photo(native)
    native.click("放大")
    native.click("右移")
    assert saved_background(native) == original, "Editing published the candidate before Apply"
    native.capture("appearance-unpublished-preview")
    native.click("取消", bottom=True)
    wait_for(lambda: not private_images(native), "Cancel did not release its uncommitted candidate image")
    assert saved_background(native) == original
    pick_photo(native)
    native.click("放大")
    native.click("右移")
    native.click("应用背景")
    wait_for(lambda: not native.has("应用背景"), "Apply did not return to appearance settings")
    assert saved_background(native) != original
    images = private_images(native)
    assert len(images) == 1 and list(images.values()) == [image_digest], "The private image changed at import"
    native.reveal_any("自定义图片", toward_start=True)
    native.capture("appearance-custom-applied")
    applied = read_domains(native, images)
    native.restart()
    assert saved_background(native) == applied and private_images(native) == images
    open_appearance(native)
    native.reveal_any("自定义图片")
    native.click("调整构图")
    native.capture("appearance-reopened-composition")
    native.click("左移")
    native.click("取消", bottom=True)
    assert saved_background(native) == applied and private_images(native) == images
    open_appearance(native)
    native.click("自动匹配系统明暗外观")
    wait_for(lambda: theme_mode(native) == "system", "The system-theme choice was not persisted")
    native.set_switch("减少动效", True)
    native.capture("appearance-reduce-motion")
    native.set_switch("减少动效", False)
    native.set_switch("视差动效", False)
    native.set_switch("视差动效", True)
    applied = saved_background(native)
    for night, label in (("yes", "dark"), ("no", "light")):
        native.adb("shell", "cmd", "uimode", "night", night)
        native.domain_home("流水")
        native.reveal_any("TaggedMeal")
        native.capture("appearance-system-" + label)
        assert saved_background(native) == applied
    open_appearance(native)
    native.click("恢复主题背景")
    wait_for(lambda: not private_images(native), "Restore theme did not release the previously applied image")
    native.restart()
    open_appearance(native)
    native.reveal_any("跟随主题")
    native.capture("appearance-restored-theme-after-restart")
    assert not private_images(native) and saved_background(native) != applied
    return {"unpublished_cancel": True, "original_image_sha256": image_digest,
        "applied_preferences_sha256": applied, "restart_retained": True,
        "edit_cancel_retained": True, "restored_theme_after_restart": True}
