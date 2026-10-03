"""Disposable cloud Mac probe. Contains no installation or upload credentials."""
import hashlib
import json
from pathlib import Path
import plistlib
import subprocess


out = Path("shortcut-signing-probe")
out.mkdir(exist_ok=True)
workflow = {
    "WFWorkflowClientVersion": "900",
    "WFWorkflowMinimumClientVersion": 900,
    "WFWorkflowName": "Ticketbox Signing Probe",
    "WFWorkflowIcon": {"WFWorkflowIconStartColor": 4282601983, "WFWorkflowIconGlyphNumber": 59511},
    "WFWorkflowTypes": [], "WFWorkflowInputContentItemClasses": ["WFStringContentItem"],
    "WFWorkflowActions": [{"WFWorkflowActionIdentifier": "is.workflow.actions.gettext",
        "WFWorkflowActionParameters": {"WFTextActionText": "Ticketbox public artifact signing probe"}}],
}
source = out / "unsigned.shortcut"
source.write_bytes(plistlib.dumps(workflow, fmt=plistlib.FMT_BINARY))
result = {}
for name, args in [
    ("version", ["sw_vers"]),
    ("help", ["shortcuts", "sign", "--help"]),
    ("sign", ["shortcuts", "sign", "--mode", "anyone", "--input", str(source),
              "--output", str(out / "signed.shortcut")]),
]:
    try:
        call = subprocess.run(args, capture_output=True, text=True, timeout=120)
        result[name] = {"code": call.returncode, "stdout": call.stdout[-4000:], "stderr": call.stderr[-4000:]}
    except subprocess.TimeoutExpired:
        result[name] = {"timeout": True}

selected = {}
roots = [Path("/System/Library/PrivateFrameworks/WorkflowKit.framework/Resources"),
         Path("/System/Applications/Shortcuts.app/Contents/Resources")]
need = ("conditional", "gettype", "getfile", "savefile", "createfolder", "gettext", "downloadurl",
        "getdictionaryvalue", "convertimage", "matchtext", "replace", "setname", "stop", "alert", "selectphotos")
for root in roots:
    for path in root.rglob("*.plist") if root.exists() else []:
        try:
            value = plistlib.loads(path.read_bytes())
        except Exception:
            continue
        if isinstance(value, dict):
            for key, item in value.items():
                if key.startswith("is.workflow.actions.") and any(part in key for part in need):
                    selected[key] = item
(out / "actions.json").write_text(json.dumps(selected, ensure_ascii=False, indent=2, default=str))
result["action_count"] = len(selected)
result["action_sources"] = [str(path) for root in roots if root.exists() for path in root.glob("*Action*")]
signed = out / "signed.shortcut"
if signed.exists():
    result["signed"] = {"bytes": signed.stat().st_size, "sha256": hashlib.sha256(signed.read_bytes()).hexdigest()}
(out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps(result, ensure_ascii=False, indent=2))
raise SystemExit(0 if result.get("sign", {}).get("code") == 0 and signed.exists() else 1)
