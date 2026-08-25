from __future__ import annotations

from pathlib import Path

WINDOWS = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
ISS = WINDOWS / "installer" / "ticketbox.iss"
LIFECYCLE = WINDOWS / "lifecycle"


FORBIDDEN_TOKENS = (
    "windows_lifecycle_receipt.ps1",
    "windows_owner_handoff.ps1",
    "hold_installer_lifecycle_lock.ps1",
    "DATABASE_GENERATION_PROGRAM.json",
    "ticketbox-windows-lifecycle-receipt-v9",
    "install_bundled_services.ps1",
    "prepare_bundled_upgrade.ps1",
)


def _iter_text_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() in {".pyc", ".png", ".ico", ".exe"}:
            continue
        files.append(path)
    return files


def test_new_tree_does_not_import_old_packaging_owners() -> None:
    roots = (WINDOWS / "installer", WINDOWS / "lifecycle", WINDOWS / "build")
    files: list[Path] = []
    for root in roots:
        if root.exists():
            files.extend(_iter_text_files(root))
    for path in files:
        if path.name in {"check_source_inputs.ps1", "ticketbox.iss", "build_installer.ps1"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        lower = text.lower()
        assert "backend/packaging" not in lower.replace("\\", "/")
        assert "backend\\packaging" not in text
        for token in FORBIDDEN_TOKENS:
            assert token not in text, f"{path} still names {token}"


def test_iss_prepare_is_readonly_and_provision_fails_setup_without_committed_result() -> None:
    text = ISS.read_text(encoding="utf-8-sig")
    assert "[Setup]" in text
    assert "PrivilegesRequired=admin" in text
    assert "PrepareToInstall" in text
    assert "TicketboxActiveOperationIsResumable" in text
    assert "FileExists(BindingPath) and (not TicketboxActiveOperationIsResumable())" in text
    assert "Utf8Encode(Payload)" in text
    assert "AnsiString(Payload)" not in text
    assert "Command := 'resume'" in text
    assert "TicketboxLifecycle.exe" in text
    assert not any(line.strip() == "[Run]" for line in text.splitlines())
    assert "AfterInstall: TicketboxProvision" not in text
    assert "TicketboxLifecycleParams" in text
    assert "topic_installorder" in text
    assert "waituntilterminated" in text.lower()
    assert "ewWaitUntilTerminated" in text
    assert "GetCustomSetupExitCode" not in text
    assert "CurStepChanged" in text
    assert "ssPostInstall" in text
    assert "RaiseException" in text
    assert "TicketboxResultIsCommitted" in text
    assert "ResultCode <> 0" in text
    assert "Observed <> OperationId" in text
    assert '"ok": false' in text
    assert "active.json" in text
    assert "resume" in text
    assert '"ok": true' in text
    assert '"phase": "committed"' in text
    assert "last-result.json" not in text
    assert "ticketbox-install-result.json" in text
    assert "topic_scriptevents" in text
    assert "NotifyAfterInstallEntry" in text
    files_section = text.split("[Files]", 1)[1].split("[", 1)[0]
    assert "TicketboxBackendLauncher.exe" not in files_section
    assert "vc_redist.x64.exe" in files_section
    assert "dontcopy" not in files_section.lower()
    assert "ExtractTemporaryFile" not in text
    assert "VCRUNTIME140.dll" in text
    assert "install_bundled_services.ps1" not in text
    assert "powershell" not in text.lower()
    assert "GetSHA256OfFile" in text
    assert "release_manifest_sha256" in text
    prepare = text.split("function PrepareToInstall", 1)[1].split("end;", 1)[0]
    assert "TicketboxEnsureMsvcRuntime" not in prepare
    for token in FORBIDDEN_TOKENS:
        assert token not in text


def test_old_fresh_iss_is_not_the_shipped_installer() -> None:
    old = REPO / "backend" / "packaging" / "ticketbox-installer.iss"
    assert not old.exists(), "old Inno recipe must be physically deleted from shipment"


def test_installer_verifies_msvc_runtime_is_not_older_than_bundled_redist() -> None:
    text = ISS.read_text(encoding="utf-8-sig")

    assert "GetVersionNumbersString(TicketboxMsvcRedistSource)" in text
    assert "GetPackedVersion(RuntimePath, InstalledVersion)" in text
    assert "StrToVersion(TicketboxRequiredMsvcRuntimeVersion, RequiredVersion)" in text
    assert "ComparePackedVersion(InstalledVersion, RequiredVersion) < 0" in text
