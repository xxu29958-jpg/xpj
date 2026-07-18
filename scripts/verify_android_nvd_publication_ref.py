from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

_BRANCH = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._/-]{0,253}[A-Za-z0-9])?$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_API_VERSION = "2022-11-28"


def verify_publication_ref(
    *,
    requested_ref: str,
    default_branch: str,
    requested_sha: str,
    current_default_sha: str,
) -> None:
    if _BRANCH.fullmatch(default_branch) is None or ".." in default_branch:
        raise ValueError("default branch identity is invalid")
    expected_ref = f"refs/heads/{default_branch}"
    if requested_ref != expected_ref:
        raise ValueError(
            f"Android NVD publication is restricted to {expected_ref}"
        )
    if (
        _SHA.fullmatch(requested_sha) is None
        or _SHA.fullmatch(current_default_sha) is None
        or requested_sha != current_default_sha
    ):
        raise ValueError(
            "Android NVD publication requires the current default-branch tip"
        )


def _current_default_sha(
    *,
    api_url: str,
    repository: str,
    default_branch: str,
    token: str,
) -> str:
    if not api_url.startswith("https://"):
        raise ValueError("GitHub API URL must use HTTPS")
    if _REPOSITORY.fullmatch(repository) is None:
        raise ValueError("GitHub repository identity is invalid")
    if not token:
        raise ValueError("GitHub token is required")
    owner_repo = urllib.parse.quote(repository, safe="/")
    branch = urllib.parse.quote(default_branch, safe="")
    request = urllib.request.Request(
        f"{api_url.rstrip('/')}/repos/{owner_repo}/git/ref/heads/{branch}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": _API_VERSION,
            "User-Agent": "xpj-android-nvd-publication-guard",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        document = json.load(response)
    if not isinstance(document, dict) or not isinstance(document.get("object"), dict):
        raise ValueError("GitHub default-branch response is invalid")
    current_sha = document["object"].get("sha")
    if not isinstance(current_sha, str) or _SHA.fullmatch(current_sha) is None:
        raise ValueError("GitHub default-branch SHA is invalid")
    return current_sha


def main() -> int:
    default_branch = os.environ.get("DEFAULT_BRANCH", "")
    verify_publication_ref(
        requested_ref=os.environ.get("REQUESTED_REF", ""),
        default_branch=default_branch,
        requested_sha=os.environ.get("REQUESTED_SHA", ""),
        current_default_sha=_current_default_sha(
            api_url=os.environ.get("GITHUB_API_URL", ""),
            repository=os.environ.get("GITHUB_REPOSITORY", ""),
            default_branch=default_branch,
            token=os.environ.get("GITHUB_TOKEN", ""),
        ),
    )
    print("ANDROID_NVD_PUBLICATION_REF_VERIFIED")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        json.JSONDecodeError,
        OSError,
        TypeError,
        ValueError,
        urllib.error.URLError,
    ) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
