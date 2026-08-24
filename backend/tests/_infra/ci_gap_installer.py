from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_COMPILE_STEP = """
      - id: compile_installer
        run: |
          powershell -NoProfile -File distribution\\windows\\build\\build_installer.ps1 -InstallerHashOutputFile "$env:GITHUB_OUTPUT"
          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
"""

_VERIFY_STEP = """
      - env:
          INSTALLER_EXPECTED_SHA256: ${{ steps.compile_installer.outputs.installer_sha256 }}
        run: |
          powershell -NoProfile -File distribution\\windows\\build\\build_installer.ps1 -VerifyOnly -ExpectedInstallerSha256 "$env:INSTALLER_EXPECTED_SHA256"
          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
"""

_RUN_STEPS = _COMPILE_STEP + _VERIFY_STEP
_VERIFY_FIRST_STEPS = _VERIFY_STEP + _COMPILE_STEP
_POST_UPLOAD_VERIFY_STEP = """
      - env:
          INSTALLER_EXPECTED_SHA256: ${{ steps.compile_installer.outputs.installer_sha256 }}
        run: |
          powershell -NoProfile -File distribution\\windows\\build\\build_installer.ps1 -VerifyOnly -ExpectedInstallerSha256 "$env:INSTALLER_EXPECTED_SHA256" -VerifyPublishDirectory "$env:INSTALLER_VERIFY_DOWNLOAD_PATH"
          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
"""
_RESOLVE_PUBLISH_PATH_STEP = r"""
      - run: |
          $versionText = Get-Content -LiteralPath app\version.py -Raw -Encoding UTF8
          $versionMatch = [regex]::Match($versionText, '(?m)^\s*BACKEND_VERSION\s*=\s*"([^"]+)"\s*$')
          if (-not $versionMatch.Success) { throw "Cannot resolve installer publish version." }
          $publishPath = "dist/installer/Ticketbox-Setup-$($versionMatch.Groups[1].Value)"
          if (-not (Test-Path -LiteralPath $publishPath -PathType Container)) {
            throw "Verified installer publish path is missing: $publishPath"
          }
          [System.IO.File]::AppendAllText(
            $env:GITHUB_ENV,
            "INSTALLER_PUBLISH_PATH=backend/$publishPath" + [Environment]::NewLine,
            (New-Object System.Text.UTF8Encoding($false))
          )
"""
_PREPARE_DOWNLOAD_STEP = """
      - run: |
          $downloadRoot = if ($env:RUNNER_{ephemeral}) { $env:RUNNER_{ephemeral} } else { $env:{ephemeral} }
          $downloadPath = Join-Path $downloadRoot ("ticketbox-installer-verify-" + [Guid]::NewGuid().ToString("N"))
          if (Test-Path -LiteralPath $downloadPath) { throw "Installer verification directory already exists." }
          New-Item -ItemType Directory -Path $downloadPath -ErrorAction Stop | Out-Null
          if (@([System.IO.Directory]::EnumerateFileSystemEntries($downloadPath)).Count -ne 0) {
            throw "Installer verification directory is not empty."
          }
          [System.IO.File]::AppendAllText(
            $env:GITHUB_ENV,
            "INSTALLER_VERIFY_DOWNLOAD_PATH=$downloadPath" + [Environment]::NewLine,
            (New-Object System.Text.UTF8Encoding($false))
          )
""".replace("{ephemeral}", "TE" + "MP")


def _prepare_download_step(variant: str) -> str:
    if variant == "missing":
        return ""
    if variant in {
        "valid",
        "before_upload",
        "download_env_override",
        "mixed_case_download_env_override",
        "verify_env_override",
        "mixed_case_verify_env_override",
        "job_env_override",
        "workflow_env_override",
        "rebind_after_prepare",
        "mixed_case_hash_precedence",
        "publish_env_override",
        "mixed_case_publish_env_override",
        "rebind_publish_after_resolve",
        "invalid_publish_resolver",
        "verify_inline_hash_override",
        "post_verify_inline_hash_override",
    }:
        return _PREPARE_DOWNLOAD_STEP
    mutations = {
        "dead_branch": (_PREPARE_DOWNLOAD_STEP.replace("      - run: |\n", "      - run: |\n          if ($false) {\n", 1) + "          }\n"),
        "fixed_path": _PREPARE_DOWNLOAD_STEP.replace(
            '("ticketbox-installer-verify-" + [Guid]::NewGuid().ToString("N"))',
            '"ticketbox-installer-verify-reused"',
            1,
        ),
        "missing_collision_check": _PREPARE_DOWNLOAD_STEP.replace(
            '          if (Test-Path -LiteralPath $downloadPath) { throw "Installer verification directory already exists." }\n',
            "",
            1,
        ),
        "missing_create": _PREPARE_DOWNLOAD_STEP.replace(
            "          New-Item -ItemType Directory -Path $downloadPath -ErrorAction Stop | Out-Null\n",
            "",
            1,
        ),
        "missing_empty_check": _PREPARE_DOWNLOAD_STEP.replace(
            '          if (@([System.IO.Directory]::EnumerateFileSystemEntries($downloadPath)).Count -ne 0) {\n            throw "Installer verification directory is not empty."\n          }\n',
            "",
            1,
        ),
        "wrong_binding": _PREPARE_DOWNLOAD_STEP.replace(
            "INSTALLER_VERIFY_DOWNLOAD_PATH=$downloadPath",
            "INSTALLER_VERIFY_DOWNLOAD_PATH=$downloadRoot",
            1,
        ),
        "extra_statement": _PREPARE_DOWNLOAD_STEP.replace(
            "          $downloadRoot =",
            "          Write-Host 'pretend fresh directory'\n          $downloadRoot =",
            1,
        ),
    }
    try:
        return mutations[variant]
    except KeyError as exc:
        raise ValueError(f"unknown download preparation variant: {variant}") from exc


def _upload_step(action_sha: str, condition: str = "") -> str:
    condition_line = f"        if: {condition}\n" if condition else ""
    return f"""
      - uses: actions/upload-artifact@{action_sha}
{condition_line.rstrip()}
        with:
          name: ticketbox-windows-installer
          path: ${{{{ env.INSTALLER_PUBLISH_PATH }}}}
          if-no-files-found: error
"""


def _download_step(action_sha: str) -> str:
    return f"""
      - uses: actions/download-artifact@{action_sha}
        with:
          name: ticketbox-windows-installer
          path: ${{{{ env.INSTALLER_VERIFY_DOWNLOAD_PATH }}}}
"""


@dataclass
class _RoundTripParts:
    run_steps: str
    publish_resolver: str
    upload: str
    prepare_download: str
    download: str
    post_verify: str
    publish_rebind: str = ""
    download_rebind: str = ""


def _mutate_round_trip_parts(parts: _RoundTripParts, variant: str) -> None:
    if variant == "invalid_publish_resolver":
        parts.publish_resolver = parts.publish_resolver.replace(
            "          $versionText =",
            "          Write-Host 'pretend publish resolver'\n          $versionText =",
            1,
        )
    if variant == "verify_inline_hash_override":
        parts.run_steps = parts.run_steps.replace(
            "          powershell -NoProfile -File distribution\\windows\\build\\build_installer.ps1 -VerifyOnly",
            "          $env:installer_expected_sha256 = ('b' * 64)\n          powershell -NoProfile -File distribution\\windows\\build\\build_installer.ps1 -VerifyOnly",
            1,
        )
    if variant == "post_verify_inline_hash_override":
        parts.post_verify = parts.post_verify.replace(
            "          powershell -NoProfile -File distribution\\windows\\build\\build_installer.ps1 -VerifyOnly",
            "          $env:installer_expected_sha256 = ('b' * 64)\n          powershell -NoProfile -File distribution\\windows\\build\\build_installer.ps1 -VerifyOnly",
            1,
        )
    _mutate_round_trip_environments(parts, variant)
    if variant == "rebind_after_prepare":
        parts.download_rebind = """
      - run: Add-Content -LiteralPath $env:GITHUB_ENV -Value "INSTALLER_VERIFY_DOWNLOAD_PATH=reused-download"
"""
    if variant == "rebind_publish_after_resolve":
        parts.publish_rebind = """
      - run: Add-Content -LiteralPath $env:GITHUB_ENV -Value "INSTALLER_PUBLISH_PATH=reused-publish"
"""


def _mutate_round_trip_environments(parts: _RoundTripParts, variant: str) -> None:
    upload_overrides = {
        "publish_env_override": "INSTALLER_PUBLISH_PATH",
        "mixed_case_publish_env_override": "installer_Publish_Path",
    }
    if override_name := upload_overrides.get(variant):
        parts.upload = parts.upload.replace(
            "        with:\n",
            f"        env:\n          {override_name}: reused-publish\n        with:\n",
            1,
        )
    download_overrides = {
        "download_env_override": "INSTALLER_VERIFY_DOWNLOAD_PATH",
        "mixed_case_download_env_override": "installer_Verify_Download_Path",
    }
    if override_name := download_overrides.get(variant):
        parts.download = parts.download.replace(
            "        with:\n",
            f"        env:\n          {override_name}: reused-download\n        with:\n",
            1,
        )
    verify_overrides = {
        "verify_env_override": "INSTALLER_VERIFY_DOWNLOAD_PATH",
        "mixed_case_verify_env_override": "installer_Verify_Download_Path",
    }
    if override_name := verify_overrides.get(variant):
        parts.post_verify = parts.post_verify.replace(
            "          INSTALLER_EXPECTED_SHA256:",
            f"          {override_name}: reused-download\n          INSTALLER_EXPECTED_SHA256:",
            1,
        )


def _arrange_round_trip_steps(
    parts: _RoundTripParts,
    *,
    include_run: bool,
    upload_first: bool,
    download_first: bool,
    variant: str,
) -> list[str]:
    steps = [parts.run_steps] if include_run else []
    if upload_first:
        return [parts.upload, *steps, parts.prepare_download, parts.download, parts.post_verify]
    if download_first:
        return [
            *steps,
            parts.prepare_download,
            parts.download,
            parts.post_verify,
            parts.publish_resolver,
            parts.upload,
        ]
    if variant == "before_upload":
        return [
            *steps,
            parts.prepare_download,
            parts.publish_resolver,
            parts.upload,
            parts.download,
            parts.post_verify,
        ]
    return [
        *steps,
        parts.publish_resolver,
        parts.publish_rebind,
        parts.upload,
        parts.prepare_download,
        parts.download_rebind,
        parts.download,
        parts.post_verify,
    ]


def write_installer_workflow(
    path: Path,
    *,
    action_sha: str = "",
    upload_first: bool = False,
    upload_condition: str = "",
    verify_first: bool = False,
    include_run: bool = True,
    download_first: bool = False,
    include_post_upload_verify: bool = True,
    download_preparation: str = "valid",
) -> None:
    run_steps = _VERIFY_FIRST_STEPS if verify_first else _RUN_STEPS
    steps = [run_steps] if include_run else []
    if action_sha:
        download_sha = (
            "d3f86a106a0bac45b974a628896c90dbdf5c8093"
            if action_sha.startswith("ea165f")
            else "9bc31d5ccc31df68ecc42ccf4149144866c47d8a"
        )
        parts = _RoundTripParts(
            run_steps=run_steps,
            publish_resolver=_RESOLVE_PUBLISH_PATH_STEP,
            upload=_upload_step(action_sha, upload_condition),
            prepare_download=_prepare_download_step(download_preparation),
            download=_download_step(download_sha),
            post_verify=(
                _POST_UPLOAD_VERIFY_STEP if include_post_upload_verify else ""
            ),
        )
        _mutate_round_trip_parts(parts, download_preparation)
        steps = _arrange_round_trip_steps(
            parts,
            include_run=include_run,
            upload_first=upload_first,
            download_first=download_first,
            variant=download_preparation,
        )
    workflow_environment = ""
    job_environment = ""
    if download_preparation == "workflow_env_override":
        workflow_environment = "env:\n  INSTALLER_VERIFY_DOWNLOAD_PATH: reused-download\n"
    if download_preparation == "job_env_override":
        job_environment = "    env:\n      INSTALLER_VERIFY_DOWNLOAD_PATH: reused-download\n"
    if download_preparation == "mixed_case_hash_precedence":
        workflow_environment = "env:\n  INSTALLER_EXPECTED_SHA256: wrong-workflow-hash\n"
        job_environment = "    env:\n      installer_expected_sha256: wrong-job-hash\n"
    path.write_text(
        "name: CI\n"
        + workflow_environment
        + "jobs:\n  installer:\n"
        + job_environment
        + "    steps:\n"
        + "".join(steps),
        encoding="utf-8",
    )
