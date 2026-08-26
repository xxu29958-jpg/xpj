"""Protected-event branch and path coverage for CI command inventory."""

from __future__ import annotations

import ast
import fnmatch
import pathlib
import re
from collections.abc import Iterable

ANDROID_PROTECTED_PATHS = (
    "android/.java-version",
    "android/app/src/**",
    "android/gradle/**",
    "android/app/build.gradle.kts",
    "android/build.gradle.kts",
    "android/gradle.properties",
    "android/gradlew",
    "android/gradlew.bat",
    "android/settings.gradle.kts",
    "android/audit/test_count_baseline.txt",
)
CI_HEAVY_SCOPES = (
    "postgres",
    "backend_frozen",
    "desktop",
    "android",
    "windows",
)
_FULL_PATHS = {
    "backend/scripts/_audit_codebase.py",
    "backend/scripts/ci_scope.py",
    "backend/scripts/codebase_audit_gate.py",
    "backend/scripts/pr_delta_baselines.py",
    "backend/scripts/postgres_release_policy.py",
    "backend/scripts/ci_gap_job_scope.py",
    "backend/scripts/ci_gap_trigger_scope.py",
    "backend/scripts/_audit_ci_gap.py",
    "backend/scripts/ci_gap_release_scope.py",
    "backend/scripts/ci_gap_required_commands.py",
    "backend/scripts/release_audit.py",
    "backend/scripts/report_qualification_sha.py",
    "backend/scripts/verify_backend_ci_results.py",
}
_ALWAYS_ON_CONTRACT_PATHS = {
    "backend/tests/_infra/android_test_qualification.py",
    "backend/tests/test_android_process_qualification.py",
    "backend/tests/test_android_test_qualification.py",
    "backend/tests/test_backend_ci_results.py",
    "backend/tests/test_postgres_ci_lane_runner.py",
    "backend/tests/test_postgres_ci_topology.py",
}
_FULL_PREFIXES = (".github/workflows/", ".gitea/workflows/")
_CI_POLICY_PREFIXES = (
    "backend/scripts/ci_gap_",
    "backend/tests/test_ci_gap_",
    "backend/tests/test_audit_ci_gap",
    "backend/tests/_infra/ci_gap_",
)
_DOC_PREFIXES = ("docs/", ".agents/", ".claude/")
_DOC_FILES = {"AGENTS.md", "CLAUDE.md", "README.md", "LICENSE"}
_WINDOWS_ONLY_BACKEND_PREFIXES = ("backend/packaging/", "backend/build/")
_WINDOWS_ONLY_BACKEND_FILES = {
    "backend/requirements-build.txt",
    "backend/requirements-build.lock",
    "backend/scripts/build_backend_exe.ps1",
    "backend/scripts/start_test_pg.ps1",
    "backend/scripts/stop_test_pg.ps1",
    "backend/scripts/test_pg_ownership_contract.ps1",
    "backend/scripts/test_pg_auth_contract.ps1",
    "backend/scripts/test_pg_process_contract.ps1",
    "backend/scripts/test_pg_storage_contract.ps1",
    "backend/scripts/windows_build_provenance.ps1",
    "backend/scripts/windows_backend_build_provenance.ps1",
    "backend/scripts/windows_python_build_environment.ps1",
    "backend/tests/_infra/windows_tree.py",
}
_POSTGRES_BACKEND_PREFIXES = ("backend/tests/", "backend/audit/")
_POSTGRES_WINDOWS_BACKEND_PREFIXES = ("backend/app/", "backend/migrations/")
_POSTGRES_WINDOWS_BACKEND_FILES = {
    "backend/alembic.ini",
    "backend/requirements-dev.txt",
    "backend/scripts/test_postgres_contract.json",
}
_CROSS_RUNTIME_RELEASE_CONFIG = "backend/packaging/windows-release-config.json"
_BACKEND_RELEASE_FILES = {
    "backend/requirements.txt",
}
_WINDOWS_SECURITY_BACKEND_FILES = {
    "backend/app/services/runtime_settings_store.py",
    "backend/app/services/secure_file.py",
    "backend/app/services/secure_file_windows.py",
    "backend/app/services/secure_file_windows_acl.py",
}
_BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]
_DATASET_MAINTENANCE_ROOT_MODULES = (
    "app.database_maintenance_runtime",
    "app.dataset_maintenance_cli",
    "app.database._dataset_backup_action",
    "app.database._dataset_backup_snapshot",
    "app.database._dataset_restore_action",
    "app.database._dataset_restore_authority",
    "app.database._dataset_restore_security",
)
_FRESH_INSTALL_ROOT_MODULES = (
    "app.database._fresh_schema_upgrade",
    "app.services.identity_service",
)
_INSTALLATION_HEALTH_ROOT_MODULES = (
    "app.database._database_generation_runtime_admission",
    "app.services.installation_health_attestation",
    "app.services.installation_health_service",
)


def _app_module_source(module_name: str) -> pathlib.Path | None:
    if module_name != "app" and not module_name.startswith("app."):
        return None
    relative = pathlib.Path(*module_name.split("."))
    module = _BACKEND_ROOT / relative.with_suffix(".py")
    package = _BACKEND_ROOT / relative / "__init__.py"
    if module.is_file():
        return module
    return package if package.is_file() else None


def _module_name(path: pathlib.Path) -> str:
    relative = path.relative_to(_BACKEND_ROOT)
    parts = relative.parts[:-1] if relative.name == "__init__.py" else (*relative.parts[:-1], relative.stem)
    return ".".join(parts)


def _app_imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    module_name = _module_name(path)
    package_parts = module_name.split(".") if path.name == "__init__.py" else module_name.split(".")[:-1]
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
            continue
        if isinstance(node, ast.ImportFrom):
            if node.level:
                parent_count = len(package_parts) - node.level + 1
                if parent_count < 1:
                    continue
                prefix = package_parts[:parent_count]
                base = ".".join((*prefix, *(node.module or "").split(".")))
            else:
                base = node.module or ""
            if base:
                imported.add(base)
                imported.update(f"{base}.{alias.name}" for alias in node.names if alias.name != "*")
            continue
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "importlib"
            and node.func.attr == "import_module"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            imported.add(node.args[0].value)
    return imported


def _app_python_dependencies(root_modules: tuple[str, ...]) -> frozenset[str]:
    pending = [
        source
        for module_name in root_modules
        if (source := _app_module_source(module_name)) is not None
    ]
    visited: set[pathlib.Path] = set()
    while pending:
        source = pending.pop()
        if source in visited:
            continue
        visited.add(source)
        for imported in _app_imports(source):
            dependency = _app_module_source(imported)
            if dependency is not None and dependency not in visited:
                pending.append(dependency)
    return frozenset(
        dependency.relative_to(_BACKEND_ROOT.parent).as_posix()
        for dependency in visited
    )


def dataset_maintenance_python_dependencies() -> frozenset[str]:
    return _app_python_dependencies(_DATASET_MAINTENANCE_ROOT_MODULES)


def fresh_install_python_dependencies() -> frozenset[str]:
    return _app_python_dependencies(_FRESH_INSTALL_ROOT_MODULES)


def installation_health_python_dependencies() -> frozenset[str]:
    return _app_python_dependencies(_INSTALLATION_HEALTH_ROOT_MODULES)


_WINDOWS_DATASET_MAINTENANCE_FILES = dataset_maintenance_python_dependencies()
_WINDOWS_FRESH_INSTALL_FILES = fresh_install_python_dependencies()
_WINDOWS_INSTALLATION_HEALTH_FILES = installation_health_python_dependencies() | {
    "backend/app/main.py",
}
_WINDOWS_DATASET_MAINTENANCE_PREFIXES = (
    "backend/app/database/_dataset_",
)
_FROZEN_DESKTOP_PREFIXES = (
    "desktop/backend_manager/",
    "desktop/packaging/",
    "desktop/scripts/",
)
_FROZEN_DESKTOP_FILES = {
    "desktop/pyproject.toml",
    "desktop/requirements.txt",
    "desktop/requirements-build.txt",
    "desktop/requirements-build.lock",
}
_EXACT_SCOPE_RULES = {
    **dict.fromkeys(_DOC_FILES, ()),
    **dict.fromkeys(_WINDOWS_ONLY_BACKEND_FILES, ("windows",)),
    **dict.fromkeys(_POSTGRES_WINDOWS_BACKEND_FILES, ("postgres", "windows")),
    **dict.fromkeys(
        _BACKEND_RELEASE_FILES,
        ("postgres", "backend_frozen", "windows"),
    ),
    **dict.fromkeys(
        _WINDOWS_SECURITY_BACKEND_FILES,
        ("postgres", "backend_frozen", "windows"),
    ),
    **dict.fromkeys(
        _WINDOWS_DATASET_MAINTENANCE_FILES,
        ("postgres", "backend_frozen", "windows"),
    ),
    **dict.fromkeys(
        _WINDOWS_FRESH_INSTALL_FILES,
        ("postgres", "backend_frozen", "windows"),
    ),
    **dict.fromkeys(
        _WINDOWS_INSTALLATION_HEALTH_FILES,
        ("postgres", "backend_frozen", "windows"),
    ),
    **dict.fromkeys(_FROZEN_DESKTOP_FILES, ("desktop", "windows")),
    _CROSS_RUNTIME_RELEASE_CONFIG: ("postgres", "desktop", "windows"),
    "backend/app/version.py": ("postgres", "desktop", "windows"),
    "backend/packaging/windows-build-toolchain.json": ("postgres", "windows"),
}
_PREFIX_SCOPE_RULES = (
    (_DOC_PREFIXES, ()),
    (("android/",), ("android",)),
    (_FROZEN_DESKTOP_PREFIXES, ("desktop", "windows")),
    (("desktop/",), ("desktop",)),
    (
        _WINDOWS_DATASET_MAINTENANCE_PREFIXES,
        ("postgres", "backend_frozen", "windows"),
    ),
    (_POSTGRES_WINDOWS_BACKEND_PREFIXES, ("postgres", "backend_frozen")),
    (_WINDOWS_ONLY_BACKEND_PREFIXES, ("windows",)),
    (("distribution/",), ("windows",)),
    (_POSTGRES_BACKEND_PREFIXES, ("postgres",)),
)
_STATUS_FUNCTION = re.compile(r"(?i)\b(success|always|failure|cancelled)\s*\(")


def all_ci_scopes() -> dict[str, bool]:
    return dict.fromkeys(CI_HEAVY_SCOPES, True)


def _scopes_for_path(path: str) -> tuple[str, ...] | None:
    exact = _EXACT_SCOPE_RULES.get(path)
    if exact is not None:
        return exact
    for prefixes, scopes in _PREFIX_SCOPE_RULES:
        if path.startswith(prefixes):
            return scopes
    return None


def classify_ci_paths(paths: Iterable[str]) -> dict[str, bool]:
    result = dict.fromkeys(CI_HEAVY_SCOPES, False)
    normalized = {path.replace("\\", "/") for path in paths if path}
    if not normalized:
        return all_ci_scopes()
    normalized.difference_update(_ALWAYS_ON_CONTRACT_PATHS)

    for path in sorted(normalized):
        if path != path.strip():
            return all_ci_scopes()
        if path in _FULL_PATHS or path.startswith(_FULL_PREFIXES) or path.startswith(_CI_POLICY_PREFIXES):
            return all_ci_scopes()
        scopes = _scopes_for_path(path)
        if scopes is None:
            return all_ci_scopes()
        for scope in scopes:
            result[scope] = True
    return result


def workflow_action_requires_prior_success(value: object) -> bool:
    if value is None or value is True:
        return True
    if not isinstance(value, str):
        return False
    expression = value.strip()
    if expression.startswith("${{") and expression.endswith("}}"):
        expression = expression[3:-2].strip()
    status_functions = {match.lower() for match in _STATUS_FUNCTION.findall(expression)}
    if not status_functions:
        return True
    if status_functions != {"success"} or "||" in expression:
        return False
    return any(re.fullmatch(r"\(*\s*success\(\)\s*\)*", term, re.IGNORECASE) for term in expression.split("&&"))


def _event_configuration(workflow: dict[object, object], event_name: str) -> dict[object, object] | None:
    trigger = workflow.get("on")
    if isinstance(trigger, str):
        return {} if trigger == event_name else None
    if isinstance(trigger, list):
        return {} if event_name in {str(event) for event in trigger} else None
    if not isinstance(trigger, dict) or event_name not in trigger:
        return None
    configuration = trigger[event_name]
    if configuration is None:
        return {}
    return configuration if isinstance(configuration, dict) else None


def _string_patterns(value: object) -> tuple[str, ...] | None:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(value)
    return None


def _ordered_pattern_match(value: str, patterns: tuple[str, ...]) -> bool:
    matched = False
    for pattern in patterns:
        negated = pattern.startswith("!")
        candidate = pattern[1:] if negated else pattern
        if candidate and fnmatch.fnmatchcase(value, candidate):
            matched = not negated
    return matched


def _event_covers_main_branch(configuration: dict[object, object]) -> bool:
    branches = _string_patterns(configuration.get("branches"))
    ignored = _string_patterns(configuration.get("branches-ignore"))
    if branches is None or ignored is None:
        return False
    tag_filtered = configuration.get("tags") is not None or configuration.get("tags-ignore") is not None
    if tag_filtered and not branches:
        return False
    if branches and not _ordered_pattern_match("main", branches):
        return False
    return not (ignored and _ordered_pattern_match("main", ignored))


def _workflow_relative_path(path: pathlib.Path) -> str:
    for root in (".github", ".gitea"):
        if root in path.parts:
            index = path.parts.index(root)
            return "/".join(path.parts[index:])
    return path.as_posix()


def _protected_path_scope(
    path: pathlib.Path,
    configuration: dict[object, object],
) -> str | None:
    if configuration.get("paths-ignore") is not None:
        return None
    paths = _string_patterns(configuration.get("paths"))
    if paths is None:
        return None
    if not paths:
        return "full"
    normalized = {item.replace("\\", "/").removeprefix("./") for item in paths}
    if not set(ANDROID_PROTECTED_PATHS).issubset(normalized):
        return None
    if _workflow_relative_path(path) not in normalized:
        return None
    return "android"


def protected_workflow_scope(
    path: pathlib.Path,
    workflow: dict[object, object],
    event_name: str,
) -> str | None:
    configuration = _event_configuration(workflow, event_name)
    if configuration is None or configuration.get("types") is not None or not _event_covers_main_branch(configuration):
        return None
    return _protected_path_scope(path, configuration)
