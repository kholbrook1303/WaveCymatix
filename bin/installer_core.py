#!/usr/bin/env python3
"""Shared, dependency-free helpers for the platform installers."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from typing import Any


APP_ITEMS = (
    "bin",
    "conf",
    "docs",
    "resources",
    "pyproject.toml",
    "requirements.txt",
    "src",
    "VERSION",
)
INSTALL_ITEMS = (
    "bin",
    "conf",
    "docs",
    "resources",
    "requirements.txt",
    "VERSION",
)
LEGACY_APP_ITEMS = ("assets", "core", "lib", "WaveCymatix.py")
CONTENT_ITEMS = ("presets", "textures", "sprites")
INSTALL_PHASES = (
    "Phase 1: preflight",
    "Phase 2: prerequisites",
    "Phase 3: projectM",
    "Phase 4: WaveCymatix",
    "Phase 5: optional components",
    "Phase 6: autostart",
    "Phase 7: finalize",
)
INSTALL_CONTENT_PATHS = (
    ("projectM.presetPath", "presets"),
    ("projectM.texturePath", "textures"),
    ("projectM.texturePath", "sprites"),
)


def fail(message: str) -> None:
    raise RuntimeError(message)


def run_git(arguments: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        fail(f"git {' '.join(arguments)} failed: {detail}")
    return result.stdout.strip()


def validate_source(source: Path, output: Path) -> None:
    source = source.resolve(strict=True)
    output = output.resolve()
    validate_source_contents(source)
    try:
        source.relative_to(output)
    except ValueError:
        return
    fail(f"Source directory must not be the same as or inside the install directory: {source}")


def validate_source_contents(source: Path) -> None:
    required_paths = {
        "VERSION": (source / "VERSION").is_file(),
        "pyproject.toml": (source / "pyproject.toml").is_file(),
        "src/wavecymatix/app.py": (source / "src" / "wavecymatix" / "app.py").is_file(),
        "src/wavecymatix/core": (source / "src" / "wavecymatix" / "core").is_dir(),
    }
    missing = [name for name, exists in required_paths.items() if not exists]
    if missing:
        fail(
            f"Selected WaveCymatix source is missing required paths: "
            f"{', '.join(missing)}. This ref cannot be installed. Verify the ref "
            "or use -LocalInstall or -Source <path> to select a complete local checkout."
        )


def resolve_latest_release(repository: str) -> str:
    repository_path = repository.removeprefix("https://github.com/").removesuffix(".git").strip("/")
    if repository_path.count("/") != 1:
        fail(f"Expected a GitHub owner/repository URL, got: {repository}")
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository_path}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "WaveCymatix-installer"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            release = json.load(response)
    except (OSError, ValueError) as error:
        fail(f"Could not resolve the latest stable WaveCymatix release: {error}")
    if not isinstance(release, dict):
        fail("GitHub latest-release response was not a JSON object.")
    tag = release.get("tag_name")
    if not isinstance(tag, str) or not tag:
        fail("GitHub latest-release response did not contain a tag_name.")
    return tag


def checkout(repository: str, ref: str, cache: Path) -> tuple[Path, str, str]:
    cache.parent.mkdir(parents=True, exist_ok=True)
    if not (cache / ".git").is_dir():
        if cache.exists():
            shutil.rmtree(cache)
        run_git(["clone", "--filter=blob:none", "--no-checkout", repository, str(cache)])

    requested_ref = resolve_latest_release(repository) if ref == "latest" else ref
    run_git(["fetch", "--force", "--prune", "origin", requested_ref], cwd=cache)
    run_git(["checkout", "--force", "--detach", "FETCH_HEAD"], cwd=cache)
    commit = run_git(["rev-parse", "HEAD"], cwd=cache)
    tag_result = subprocess.run(
        ["git", "describe", "--tags", "--exact-match", "HEAD"],
        cwd=cache,
        check=False,
        capture_output=True,
        text=True,
    )
    tag = tag_result.stdout.strip() if tag_result.returncode == 0 else ""
    return cache, commit, tag or (requested_ref if requested_ref.startswith("v") else "")


def copy_tree(source: Path, destination: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, destination, dirs_exist_ok=True, symlinks=True)
    elif source.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    else:
        fail(f"Required source item not found: {source}")


def remove_readonly(
    function: Callable[[str], Any],
    path: str,
    error: tuple[type[OSError], OSError, TracebackType | None],
) -> None:
    if not isinstance(error[1], PermissionError) or Path(path).is_symlink():
        raise error[1]
    os.chmod(path, Path(path).stat().st_mode | stat.S_IWRITE)
    function(path)


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, onerror=remove_readonly)
    elif path.exists() or path.is_symlink():
        path.unlink()


def install_files(files: list[tuple[Path, Path]]) -> None:
    if not files:
        fail("At least one component file is required.")
    staged: list[tuple[Path, Path, Path]] = []
    destinations: set[str] = set()
    try:
        for source, destination in files:
            normalized_destination = os.path.normcase(os.path.abspath(destination))
            if normalized_destination in destinations:
                fail(f"Duplicate component destination: {destination}")
            destinations.add(normalized_destination)
            if not (source.is_file() or source.is_symlink()):
                fail(f"Component file is missing: {source}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary_root = Path(
                tempfile.mkdtemp(
                    prefix=f".{destination.name}.install-",
                    dir=destination.parent,
                )
            )
            staged_path = temporary_root / destination.name
            staged.append((staged_path, destination, temporary_root))
            if source.is_symlink():
                staged_path.symlink_to(os.readlink(source))
            else:
                shutil.copy2(source, staged_path)

        for staged_path, destination, _ in staged:
            os.replace(staged_path, destination)
    finally:
        for _, _, temporary_root in staged:
            _remove_path(temporary_root)


def rollback_application_changes(output: Path) -> None:
    marker = output / ".installer-app-rollback.json"
    if not marker.is_file():
        return
    state = json.loads(marker.read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        fail(f"Invalid application rollback marker: {marker}")
    for key, allowed_items, backup_name in (
        ("content", CONTENT_ITEMS, ".content-prev"),
        ("configuration", ("conf",), ".config-prev"),
        ("legacy", LEGACY_APP_ITEMS, ".app-prev"),
    ):
        items = state.get(key, {})
        if (
            not isinstance(items, dict)
            or any(name not in allowed_items for name in items)
            or any(not isinstance(had_previous, bool) for had_previous in items.values())
        ):
            fail(f"Invalid config/content rollback marker: {marker}")
        backup_root = output / backup_name
        for name, had_previous in reversed(list(items.items())):
            destination = output / name
            saved = backup_root / name
            if had_previous:
                if saved.exists() or saved.is_symlink():
                    _remove_path(destination)
                    os.replace(saved, destination)
                elif not destination.exists():
                    fail(f"Config/content rollback item is missing: {saved}")
            else:
                _remove_path(destination)
    previous_components = state.get("manifest_components")
    if not isinstance(previous_components, dict):
        fail(f"Invalid config/content manifest rollback state: {marker}")
    manifest = _read_manifest(output)
    components = manifest.setdefault("components", {})
    if not isinstance(components, dict):
        fail("Manifest components field must be a JSON object.")
    for name in ("visual-assets",):
        previous = previous_components.get(name)
        if previous is None:
            components.pop(name, None)
        else:
            components[name] = previous
    _write_manifest(output, manifest)
    _remove_path(output / ".config-prev")
    _remove_path(output / ".content-prev")
    _remove_path(output / ".app-prev")
    marker.unlink()


def discard_install_backups(output: Path) -> None:
    for name in (
        ".config-prev",
        ".content-prev",
        ".app-prev",
        ".prev",
        ".installer-environment-backup",
        ".installer-rollback.json",
    ):
        _remove_path(output / name)
    (output / ".installer-app-rollback.json").unlink(missing_ok=True)


def stage(source: Path, output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    stage_dir = output / ".new"
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir()
    for item in APP_ITEMS:
        copy_tree(source / item, stage_dir / item)

    old_conf = output / "conf"
    if old_conf.is_dir():
        shutil.rmtree(stage_dir / "conf")
        shutil.copytree(old_conf, stage_dir / "conf", symlinks=True)
    merge_toml_config_defaults(source / "conf", stage_dir / "conf")

    legacy_artifacts = output / "bin" / "artifacts"
    runtime_artifacts = output / "runtime" / "artifacts"
    if legacy_artifacts.is_dir() and not runtime_artifacts.exists():
        runtime_artifacts.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(legacy_artifacts, runtime_artifacts, symlinks=True)
    return stage_dir


def _toml_table_ranges(lines: list[str]) -> dict[str, tuple[int, int]]:
    headers = [
        (index, match.group(1))
        for index, line in enumerate(lines)
        if (match := re.match(r"^\s*\[([A-Za-z0-9_-]+)\]\s*(?:#.*)?$", line))
    ]
    return {
        table: (
            start,
            headers[position + 1][0] if position + 1 < len(headers) else len(lines),
        )
        for position, (start, table) in enumerate(headers)
    }


def _toml_direct_key(table: str, assignment: str) -> str | None:
    key, separator, _ = assignment.partition("=")
    if not separator:
        return None
    try:
        parsed = tomllib.loads(f"[{table}]\n{key.strip()} = 0")
    except tomllib.TOMLDecodeError:
        return None
    values = parsed.get(table)
    if isinstance(values, dict) and len(values) == 1:
        parsed_key = next(iter(values))
        return parsed_key if isinstance(parsed_key, str) else None
    return None


def merge_toml_config_defaults(defaults_dir: Path, config_dir: Path) -> None:
    """Add missing shipped TOML settings without replacing local values."""
    for default_path in sorted(defaults_dir.glob("*.toml")):
        config_path = config_dir / default_path.name
        if not config_path.is_file():
            config_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(default_path, config_path)
            continue

        try:
            default_text = default_path.read_text(encoding="utf-8")
            current_text = config_path.read_text(encoding="utf-8")
            default_data = tomllib.loads(default_text)
            current_data = tomllib.loads(current_text)
        except (OSError, tomllib.TOMLDecodeError) as error:
            fail(f"Unable to merge TOML defaults for {config_path}: {error}")

        default_lines = default_text.splitlines()
        current_lines = current_text.splitlines()
        default_ranges = _toml_table_ranges(default_lines)
        current_ranges = _toml_table_ranges(current_lines)
        additions: dict[str, list[str]] = {}

        for table, defaults in default_data.items():
            if not isinstance(defaults, dict):
                continue
            existing = current_data.get(table, {})
            if not isinstance(existing, dict):
                fail(f"Expected TOML table [{table}] in {config_path}")

            if table not in current_ranges:
                start, end = default_ranges[table]
                additions.setdefault("", []).extend(default_lines[start:end])
                current_data[table] = defaults
                continue

            start, end = default_ranges[table]
            default_assignments: dict[str, int] = {}
            for index in range(start + 1, end):
                stripped = default_lines[index].strip()
                if not stripped or stripped.startswith("#"):
                    continue
                key = _toml_direct_key(table, stripped)
                if key is not None:
                    default_assignments.setdefault(key, index)

            missing = set(defaults) - set(existing)
            if not missing:
                continue

            section_additions: list[str] = []
            for key, index in default_assignments.items():
                if key not in missing:
                    continue
                comment_start = index
                while comment_start > start + 1:
                    previous = default_lines[comment_start - 1].strip()
                    if not previous.startswith("#"):
                        break
                    comment_start -= 1
                section_additions.extend(default_lines[comment_start : index + 1])
            if section_additions:
                additions.setdefault(table, []).extend(section_additions)
                current_data[table].update(
                    {key: defaults[key] for key in missing}
                )

        if not additions:
            continue

        for table, extra_lines in additions.items():
            if table == "":
                if current_lines and current_lines[-1].strip():
                    current_lines.append("")
                current_lines.extend(extra_lines)
                continue
            _, section_end = _toml_table_ranges(current_lines)[table]
            insert_at = section_end
            while insert_at > 0 and not current_lines[insert_at - 1].strip():
                insert_at -= 1
            if insert_at > 0 and current_lines[insert_at - 1].strip():
                extra_lines.insert(0, "")
            current_lines[insert_at:insert_at] = extra_lines

        merged_text = "\n".join(current_lines) + "\n"
        try:
            tomllib.loads(merged_text)
        except tomllib.TOMLDecodeError as error:
            fail(f"Merging TOML defaults produced invalid config {config_path}: {error}")
        config_path.write_text(merged_text, encoding="utf-8")


def validate(stage_dir: Path, python: str) -> None:
    for relative in (
        "src/wavecymatix/app.py",
        "src/wavecymatix/core",
        "conf/settings.toml",
        "pyproject.toml",
        "requirements.txt",
    ):
        if not (stage_dir / relative).exists():
            fail(f"Staged application is missing required path: {relative}")
    syntax_check = (
        "from pathlib import Path; import sys; "
        "root = Path(sys.argv[1]); "
        "[compile(path.read_bytes(), str(path), 'exec') for path in root.rglob('*.py')]"
    )
    result = subprocess.run(
        [python, "-c", syntax_check, str(stage_dir)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        fail(f"Staged Python compile check failed: {result.stderr.strip()}")
    package_check = (
        "from importlib.resources import files; import wavecymatix; "
        "assert files('wavecymatix').joinpath('assets', 'play-circle.png').is_file()"
    )
    result = subprocess.run(
        [python, "-c", package_check],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        fail(f"Installed WaveCymatix package validation failed: {result.stderr.strip()}")


def commit(
    output: Path,
    include_app: bool = True,
    mark_application_in_progress: bool = False,
) -> None:
    stage_dir = output / ".new"
    if not stage_dir.is_dir():
        fail(f"Staged application directory does not exist: {stage_dir}")
    staged_content = output / ".content-new"
    backup_content = output / ".content-prev"
    app_items = [item for item in INSTALL_ITEMS] if include_app else []
    content_items = (
        [item for item in CONTENT_ITEMS]
        if staged_content.exists()
        else []
    )
    if not app_items and not content_items:
        shutil.rmtree(stage_dir)
        return
    configuration_backup = output / ".config-prev"
    application_backup = output / ".app-prev"
    if "conf" in app_items:
        _remove_path(configuration_backup)
        configuration_backup.mkdir()
    if app_items:
        _remove_path(application_backup)
        application_backup.mkdir()
    if content_items:
        if backup_content.exists():
            shutil.rmtree(backup_content)
        backup_content.mkdir()
    manifest = _read_manifest(output)
    components = manifest.get("components")
    if not isinstance(components, dict):
        components = {}
    transaction = {
        "configuration": {
            "conf": (output / "conf").exists()
        } if "conf" in app_items else {},
        "content": {
            item: (output / item).exists() for item in content_items
        },
        "legacy": {
            item: (output / item).exists() or (output / item).is_symlink()
            for item in LEGACY_APP_ITEMS
        } if app_items else {},
        "manifest_components": {
            name: json.loads(json.dumps(components[name]))
            if name in components
            else None
            for name in ("visual-assets",)
        },
    }
    transaction_marker = output / ".installer-app-rollback.json"
    _write_json_atomic(transaction_marker, transaction)
    if mark_application_in_progress:
        update_manifest_component(output, "application", "in_progress")
    try:
        for item in app_items:
            staged_item = stage_dir / item
            destination = output / item
            if not staged_item.exists():
                fail(f"Staged item does not exist: {item}")
            if item == "conf" and destination.exists():
                os.replace(destination, configuration_backup / item)
            else:
                _remove_path(destination)
            os.replace(staged_item, destination)
        for item in content_items:
            staged_item = staged_content / item
            destination = output / item
            if not staged_item.exists():
                fail(f"Staged content item does not exist: {item}")
            if destination.exists():
                os.replace(destination, backup_content / item)
            os.replace(staged_item, destination)
        for item, had_previous in transaction["legacy"].items():
            if had_previous:
                os.replace(output / item, application_backup / item)
    except Exception:
        rollback_application_changes(output)
        raise
    finally:
        if stage_dir.exists():
            shutil.rmtree(stage_dir)
        if staged_content.exists():
            shutil.rmtree(staged_content)


def prepare_application(
    source: Path,
    output: Path,
    python: str,
    required_python: str,
    supported_api: int,
    assets_repository: str,
    assets_ref: str,
    reinstall_venv: bool = False,
    refresh_content: bool = False,
    reset_config: bool = False,
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    if read_manifest_value(output, "status") != "in_progress":
        fail("Cannot prepare the application outside an active installer operation.")
    had_user_config = (output / "conf" / "settings.toml").is_file()
    if reset_config:
        existing_config = output / "conf"
        if existing_config.is_dir():
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = output / f"conf.backup-{timestamp}"
            shutil.copytree(existing_config, backup)

    stage_dir = stage(source.resolve(), output.resolve())
    if reset_config:
        shutil.rmtree(stage_dir / "conf")
        shutil.copytree(source / "conf", stage_dir / "conf", symlinks=True)
    verify_installer_api(stage_dir / "VERSION", supported_api)

    content = prepare_content(
        assets_repository,
        assets_ref,
        output / "runtime" / "cache" / "visual-assets",
        output,
        refresh_content,
    )

    update_manifest_component(output, "python", "in_progress")
    environment = output / ".venv"
    environment_created = False
    if reinstall_venv:
        for legacy_name in ("venv", ".venv", "env"):
            legacy_environment = output / legacy_name
            if legacy_environment.exists():
                _remove_path(legacy_environment)

    environment_python = _venv_python(environment)
    if not environment_python.is_file():
        if environment.exists():
            _remove_path(environment)
        _run_python(python, ["-m", "venv", str(environment)])
        environment_created = True

    actual_version = _python_version(str(environment_python))
    if actual_version != required_python:
        _remove_path(environment)
        _run_python(python, ["-m", "venv", str(environment)])
        environment_created = True
        actual_version = _python_version(str(environment_python))
    if actual_version != required_python:
        fail(
            f"Virtual environment Python version {actual_version} does not match "
            f"required version {required_python}."
        )

    requirements = stage_dir / "requirements.txt"
    requirements_digest = requirements_hash(requirements)
    stamped_digest = read_manifest_value(output, "components.python.requirements_sha256")
    if environment_created or stamped_digest != requirements_digest:
        _run_python(
            str(environment_python),
            ["-m", "pip", "install", "-r", str(requirements)],
        )
    _run_python(
        str(environment_python),
        ["-m", "pip", "install", "--no-deps", str(stage_dir)],
    )

    update_manifest_component(output, "python", "installed", {
        "version": _full_python_version(str(environment_python)),
        "venv": environment.name,
        "requirements_sha256": requirements_digest,
    })
    for directory in ("data", "preset_backup"):
        (output / directory).mkdir(parents=True, exist_ok=True)

    return {
        "stage_dir": str(stage_dir),
        "had_user_config": had_user_config and not reset_config,
        "venv_path": str(environment),
        "venv_python": str(environment_python),
        "python_version": actual_version,
        "requirements_sha256": requirements_digest,
        "assets_path": content["path"],
        "assets_ref": content["ref"],
        "assets_commit": content["commit"],
        "assets_staged": content["staged"],
    }


def _venv_python(environment: Path) -> Path:
    if os.name == "nt":
        return environment / "Scripts" / "python.exe"
    return environment / "bin" / "python"


def _run_python(python: str, arguments: list[str]) -> None:
    result = subprocess.run(
        [python, *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        fail(f"{python} {' '.join(arguments)} failed: {detail}")


def _python_version(python: str) -> str:
    result = subprocess.run(
        [
            python,
            "-c",
            "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        fail(f"Unable to query Python version from {python}: {result.stderr.strip()}")
    return result.stdout.strip()


def _full_python_version(python: str) -> str:
    result = subprocess.run(
        [python, "-c", "import platform; print(platform.python_version())"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        fail(f"Unable to query Python version from {python}: {result.stderr.strip()}")
    return result.stdout.strip()


def commit_application(
    stage_dir: Path,
    output: Path,
    python: str,
    source_ref: str,
    source_commit: str,
    assets_ref: str,
    assets_commit: str,
    configure_default_paths: bool = False,
    force_app_files: bool = False,
) -> None:
    ensure_install_paths(
        stage_dir / "conf" / "settings.toml", output, configure_default_paths
    )
    validate(stage_dir, python)
    staged_version = read_app_version(stage_dir / "src" / "wavecymatix" / "VERSION")
    read_version(stage_dir / "VERSION")
    manifest = _read_manifest(output)
    components = manifest.get("components")
    application = components.get("application") if isinstance(components, dict) else None
    no_op = (
        not force_app_files
        and bool(source_commit)
        and isinstance(application, dict)
        and application.get("status") == "installed"
        and application.get("commit") == source_commit
        and application.get("version") == staged_version
        and (output / "requirements.txt").is_file()
        and requirements_hash(output / "requirements.txt")
        == requirements_hash(stage_dir / "requirements.txt")
        and (output / "conf" / "settings.toml").is_file()
        and (output / "conf" / "settings.toml").read_bytes()
        == (stage_dir / "conf" / "settings.toml").read_bytes()
        and not any(
            (output / item).exists() or (output / item).is_symlink()
            for item in LEGACY_APP_ITEMS
        )
    )
    if not no_op:
        commit(output, mark_application_in_progress=True)
    else:
        commit(output, include_app=False)
    update_manifest_component(
        output,
        "application",
        "installed",
        {
            "version": staged_version,
            "ref": source_ref,
            "commit": source_commit,
        },
    )
    update_manifest_component(
        output,
        "visual-assets",
        "installed",
        {"ref": assets_ref, "commit": assets_commit},
    )


def stage_content(source: Path, output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    staged = output / ".content-new"
    if staged.exists():
        shutil.rmtree(staged)
    staged.mkdir()

    for item in CONTENT_ITEMS:
        source_dir = source / item
        if not source_dir.is_dir():
            fail(f"Visual-assets checkout is missing required directory: {item}")
        shutil.copytree(source_dir, staged / item, symlinks=True)
    return staged


def content_is_current(output: Path, commit_hash: str, force: bool = False) -> bool:
    if force or not commit_hash:
        return False
    recorded_commit = read_manifest_value(output, "components.visual-assets.commit")
    if recorded_commit is None:
        recorded_commit = read_manifest_value(output, "content.visual_assets_commit")
    if recorded_commit != commit_hash:
        return False
    return all((output / item).is_dir() for item in CONTENT_ITEMS)


def prepare_content(
    repository: str, ref: str, cache: Path, output: Path, force: bool = False
) -> dict[str, Any]:
    path, commit_hash, tag = checkout(repository, ref, cache)
    current = content_is_current(output, commit_hash, force)
    if not current:
        update_manifest_component(output, "visual-assets", "in_progress")
        stage_content(path, output)
    return {
        "path": str(path),
        "commit": commit_hash,
        "tag": tag,
        "ref": tag or ref,
        "current": current,
        "staged": not current,
    }


def ensure_install_paths(
    config: Path, output: Path, configure_default_paths: bool = False
) -> None:
    if not config.is_file():
        fail(f"Configuration file not found: {config}")

    output = output.resolve()
    if configure_default_paths:
        set_toml_values(
            config,
            {
                "general": {
                    "playlistDbPath": str(output / "data" / "media_library.db")
                },
                "projectm": {
                    "projectM.presetDeleteBackupPath": str(output / "preset_backup")
                },
            },
        )

    try:
        parsed = tomllib.loads(config.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        fail(f"Unable to read TOML configuration {config}: {error}")

    def normalized_path(value: str) -> str:
        return os.path.normcase(os.path.normpath(os.path.expanduser(value)))

    for key_prefix, relative_path in INSTALL_CONTENT_PATHS:
        desired = str(output / relative_path)
        settings = parsed.setdefault("projectm", {})
        if not isinstance(settings, dict):
            fail(f"Invalid TOML table [projectm] in {config}")
        values_by_lower_name = {name.lower(): value for name, value in settings.items()}
        key_base = key_prefix.lower()
        default_path = normalized_path(str(Path("/opt/WaveCymatix") / relative_path))
        default_keys = {
            name
            for name, value in settings.items()
            if (
                name.lower() == key_base
                or re.fullmatch(rf"{re.escape(key_base)}\.\d+", name.lower())
            )
            and isinstance(value, str)
            and normalized_path(value) == default_path
        }
        if default_keys:
            replacements = {name: desired for name in default_keys}
            set_toml_values(config, {"projectm": replacements})
            settings.update(replacements)
            values_by_lower_name = {
                name.lower(): value for name, value in settings.items()
            }

        used_indexes = {
            int(name[len(key_base) + 1 :])
            for name in values_by_lower_name
            if name.startswith(f"{key_base}.")
            and name[len(key_base) + 1 :].isdigit()
        }
        desired_normalized = normalized_path(desired)
        if any(
            isinstance(value, str) and normalized_path(value) == desired_normalized
            for name, value in values_by_lower_name.items()
            if name == key_base or name.startswith(f"{key_base}.")
        ):
            continue

        index = 1
        while index in used_indexes:
            index += 1
        set_toml_values(config, {"projectm": {f"{key_prefix}.{index}": desired}})
        parsed["projectm"][f"{key_prefix}.{index}"] = desired


def _toml_key(key: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_-]+", key):
        return key
    return json.dumps(key, ensure_ascii=False)


def _toml_value(value: str) -> str:
    if value.lower() in ("true", "false"):
        return value.lower()
    try:
        parsed_value = tomllib.loads(f"value = {value}")["value"]
    except tomllib.TOMLDecodeError:
        parsed_value = value
    if isinstance(parsed_value, (bool, int, float)):
        if isinstance(parsed_value, bool):
            return str(parsed_value).lower()
        return str(parsed_value)
    return json.dumps(value, ensure_ascii=False)


def set_toml_values(config: Path, values: dict[str, dict[str, str]]) -> None:
    if not config.is_file():
        fail(f"Configuration file not found: {config}")

    text = config.read_text(encoding="utf-8")
    lines = text.splitlines()

    for section_name, section_values in values.items():
        if not re.fullmatch(r"[A-Za-z0-9_-]+", section_name):
            fail(f"Invalid TOML table name: {section_name}")
        section_header = f"[{section_name}]"
        section_start = next(
            (
                index
                for index, line in enumerate(lines)
                if line.strip().lower() == section_header.lower()
            ),
            None,
        )
        if section_start is None:
            if lines and lines[-1].strip():
                lines.append("")
            lines.append(section_header)
            section_start = len(lines) - 1
            section_end = len(lines)
        else:
            section_end = next(
                (
                    index
                    for index in range(section_start + 1, len(lines))
                    if re.match(r"^\s*\[", lines[index])
                ),
                len(lines),
            )

        for key, value in section_values.items():
            if (
                not key
                or "=" in key
                or "\r" in key
                or "\n" in key
                or "\r" in value
                or "\n" in value
            ):
                fail(f"Invalid TOML setting: {section_name}.{key}")
            key_pattern = re.compile(
                rf"^\s*(?:{re.escape(_toml_key(key))}|{re.escape(key)})\s*=.*$",
                re.IGNORECASE,
            )
            matching_lines = [
                index
                for index in range(section_start + 1, section_end)
                if not lines[index].lstrip().startswith("#")
                and key_pattern.match(lines[index])
            ]
            if matching_lines:
                for index in matching_lines:
                    lines[index] = f"{_toml_key(key)} = {_toml_value(value)}"
            else:
                lines.insert(section_end, f"{_toml_key(key)} = {_toml_value(value)}")
                section_end += 1

    if lines != text.splitlines():
        config.write_text("\n".join(lines) + "\n", encoding="utf-8")


def requirements_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_version(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            fail(f"Invalid VERSION entry: {line}")
        key, value = (part.strip() for part in line.split("=", 1))
        if key in values or not value:
            fail(f"Invalid or duplicate VERSION key: {key}")
        values[key] = value
    if "INSTALLER_API" not in values:
        fail("VERSION must define INSTALLER_API.")
    if not values["INSTALLER_API"].isdigit():
        fail("INSTALLER_API in VERSION must be an integer.")
    return values


def read_app_version(path: Path) -> str:
    version = path.read_text(encoding="utf-8").strip()
    if not version:
        fail(f"Application version is missing from {path}.")
    return version


def verify_installer_api(path: Path, supported_api: int) -> None:
    version = read_version(path)
    required_api = int(version["INSTALLER_API"])
    if required_api > supported_api:
        fail(
            f"This source requires installer API {required_api}; "
            f"this installer supports API {supported_api}. "
            "Download and run the installer from the selected source ref."
        )


def resolve_source(
    repository: str | None,
    source: Path | None,
    ref: str,
    cache: Path,
    output: Path,
    supported_api: int,
) -> dict[str, str]:
    tag = ""
    if source is not None:
        source_path = source.resolve(strict=True)
        validate_source(source_path, output)
        commit_hash = (
            run_git(["rev-parse", "HEAD"], cwd=source_path)
            if (source_path / ".git").exists()
            else ""
        )
        resolved_ref = "local"
    else:
        if not repository:
            fail("A repository URL or local source path is required.")
        source_path, commit_hash, tag = checkout(repository, ref, cache)
        resolved_ref = tag or ref

    if source is None:
        validate_source_contents(source_path)
    verify_installer_api(source_path / "VERSION", supported_api)
    return {
        "path": str(source_path),
        "commit": commit_hash,
        "tag": tag,
        "ref": resolved_ref,
    }


def _read_manifest(output: Path) -> dict[str, Any]:
    manifest_path = output / ".install-state.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            fail(f"Cannot read install manifest {manifest_path}: {error}")
        if not isinstance(manifest, dict):
            fail(f"Install manifest must contain a JSON object: {manifest_path}")
    else:
        manifest = {}
    return manifest


def _migrate_manifest(manifest: dict[str, Any]) -> None:
    has_legacy_state = any(
        key in manifest
        for key in (
            "installed_at",
            "app_version",
            "python",
            "projectm",
            "content",
            "source",
            "options",
            "last_mode",
            "last_profile",
        )
    )
    if "schema_version" not in manifest and has_legacy_state:
        manifest.pop("installed_at", None)
        manifest["legacy_state_migrated_at"] = datetime.now(timezone.utc).isoformat()
    components = manifest.setdefault("components", {})
    if not isinstance(components, dict):
        fail("Manifest components field must be a JSON object.")

    def migrate_component(
        name: str, version: Any, details: dict[str, Any] | None = None
    ) -> None:
        if version is None and not details:
            return
        existing = components.get(name)
        if not isinstance(existing, dict):
            existing = {"status": "unverified"}
            components[name] = existing
        if version is not None:
            existing["version"] = version
        if details:
            for key, value in details.items():
                if value is not None:
                    existing[key] = value

    source = manifest.pop("source", {})
    if not isinstance(source, dict):
        source = {}
    migrate_component(
        "application",
        manifest.pop("app_version", None),
        {"ref": source.get("ref"), "commit": source.get("commit")},
    )

    python_details = manifest.pop("python", {})
    if isinstance(python_details, dict):
        migrate_component(
            "python",
            python_details.get("version"),
            {
                "venv": python_details.get("venv"),
                "requirements_sha256": python_details.get("requirements_sha256"),
            },
        )

    projectm_details = manifest.pop("projectm", {})
    if isinstance(projectm_details, dict):
        migrate_component(
            "projectm",
            projectm_details.get("version"),
            {
                "renderer": projectm_details.get("renderer"),
                "ref": projectm_details.get("ref"),
                "commit": projectm_details.get("commit"),
                "artifacts_sha256": projectm_details.get("artifacts_sha256"),
                "built_with": projectm_details.get("built_with"),
            },
        )

    content_details = manifest.pop("content", {})
    if isinstance(content_details, dict):
        migrate_component(
            "visual-assets",
            None,
            {
                "ref": content_details.get("visual_assets_ref"),
                "commit": content_details.get("visual_assets_commit"),
            },
        )

    old_options = manifest.pop("options", {})
    if isinstance(old_options, dict):
        if isinstance(old_options.get("autostart"), bool):
            migrate_component(
                "autostart",
                None,
                {"state": "installed" if old_options["autostart"] else "removed"},
            )
        plugins = old_options.get("plugins")
        if isinstance(plugins, list):
            for plugin in plugins:
                if isinstance(plugin, str) and plugin:
                    migrate_component(f"plugin-{plugin}", None, {"state": "installed"})
        if isinstance(old_options.get("hyperion"), bool):
            migrate_component(
                "hyperion",
                None,
                {
                    "state": "installed"
                    if old_options["hyperion"]
                    else "removed"
                },
            )

    manifest.pop("last_mode", None)
    manifest.pop("last_profile", None)
    manifest.setdefault("schema_version", 1)


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
    ) as temporary:
        json.dump(value, temporary, indent=2, sort_keys=True)
        temporary.write("\n")
        temporary_path = Path(temporary.name)
    try:
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _write_manifest(output: Path, manifest: dict[str, Any]) -> None:
    _write_json_atomic(output / ".install-state.json", manifest)


def manifest_operation(
    output: Path, action: str, error: str | None = None
) -> None:
    rollback_errors: list[str] = []
    if action == "begin":
        rollback_application_changes(output)
        discard_install_backups(output)
    elif action == "failed":
        try:
            rollback_application_changes(output)
        except (OSError, RuntimeError) as rollback_error:
            rollback_errors.append(str(rollback_error))

    now = datetime.now(timezone.utc).isoformat()
    manifest = _read_manifest(output)
    if action == "begin":
        _migrate_manifest(manifest)
        components = manifest.get("components")
        if manifest.get("status") == "in_progress" and isinstance(components, dict):
            for component in components.values():
                if isinstance(component, dict) and component.get("status") == "in_progress":
                    component["status"] = "failed"
                    component["updated_at"] = now
                    component["error"] = (
                        "Previous installer attempt ended before completion."
                    )
        manifest["status"] = "in_progress"
        manifest["attempt"] = {"status": "in_progress", "started_at": now}
    elif action in {"succeeded", "failed"}:
        attempt = manifest.get("attempt")
        if not isinstance(attempt, dict):
            attempt = {}
        components = manifest.get("components")
        if action == "succeeded" and isinstance(components, dict):
            unfinished = [
                name
                for name, component in components.items()
                if isinstance(component, dict) and component.get("status") == "in_progress"
            ]
            if unfinished:
                fail(
                    "Cannot mark installation successful while components are still "
                    f"in progress: {', '.join(unfinished)}"
                )
        attempt.update({"status": action, "finished_at": now})
        combined_error = error
        if rollback_errors:
            rollback_detail = "; ".join(rollback_errors)
            combined_error = (
                f"{combined_error}; rollback failed: {rollback_detail}"
                if combined_error
                else f"Rollback failed: {rollback_detail}"
            )
        if combined_error:
            attempt["error"] = combined_error
        else:
            attempt.pop("error", None)
        manifest["attempt"] = attempt
        manifest["status"] = action
        if action == "succeeded":
            if not manifest.get("installed_at"):
                manifest["installed_at"] = now
            manifest["updated_at"] = now
        else:
            components = manifest.get("components")
            if isinstance(components, dict):
                for component in components.values():
                    if isinstance(component, dict) and component.get("status") == "in_progress":
                        component["status"] = "failed"
                        component["updated_at"] = now
                        if combined_error:
                            component["error"] = combined_error
    else:
        fail(f"Unsupported manifest operation action: {action}")
    _write_manifest(output, manifest)
    if action == "succeeded":
        discard_install_backups(output)
    if rollback_errors:
        fail(f"Installer rollback failed: {'; '.join(rollback_errors)}")


def update_manifest_component(
    output: Path,
    name: str,
    status: str,
    details: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    if not name or any(part in name for part in (".", "/", "\\")):
        fail(f"Invalid manifest component name: {name}")
    if status not in {"in_progress", "installed", "removed", "failed"}:
        fail(f"Unsupported manifest component status: {status}")
    now = datetime.now(timezone.utc).isoformat()
    manifest = _read_manifest(output)
    components = manifest.setdefault("components", {})
    if not isinstance(components, dict):
        fail("Manifest components field must be a JSON object.")

    component = components.get(name)
    if not isinstance(component, dict):
        component = {}
        components[name] = component
    if status == "in_progress":
        component.clear()
        component.update({"status": status, "updated_at": now})
    elif status == "failed":
        component.clear()
        component.update({"status": status, "updated_at": now})
        if error:
            component["error"] = error
    else:
        component.clear()
        component.update({"status": status, "updated_at": now})
        if details:
            component.update(details)
        if error:
            component["error"] = error
    _write_manifest(output, manifest)


def projectm_component(
    output: Path,
    action: str,
    version: str,
    renderer: str,
    source_type: str,
    ref: str,
    commit: str,
    toolchain: str,
    build_settings: dict[str, Any],
    artifact_paths: dict[str, Path],
    allow_legacy: bool = False,
) -> dict[str, Any]:
    if not artifact_paths:
        fail("At least one projectM runtime artifact is required.")
    artifacts_sha256: dict[str, str] = {}
    for name, path in artifact_paths.items():
        if not name or "=" in name:
            fail(f"Invalid projectM artifact name: {name}")
        if not path.is_file():
            if action == "stamp":
                fail(f"ProjectM runtime artifact is missing: {path}")
            return {"matches": False, "artifacts_sha256": {}}
        artifacts_sha256[name] = hashlib.sha256(path.read_bytes()).hexdigest()

    details = {
        "version": version,
        "renderer": renderer,
        "source_type": source_type,
        "ref": ref,
        "commit": commit,
        "toolchain": toolchain,
        "build_settings": build_settings,
        "artifacts_sha256": artifacts_sha256,
    }
    if action == "stamp":
        update_manifest_component(output, "projectm", "installed", details)
        return {"matches": True, "artifacts_sha256": artifacts_sha256}
    if action != "check":
        fail(f"Unsupported projectM component action: {action}")

    manifest = _read_manifest(output)
    components = manifest.get("components")
    current = components.get("projectm") if isinstance(components, dict) else None
    if not isinstance(current, dict) or current.get("status") != "installed":
        return {"matches": False, "artifacts_sha256": artifacts_sha256}

    for key in ("version", "renderer", "ref", "commit"):
        if current.get(key, "") != details[key]:
            return {"matches": False, "artifacts_sha256": artifacts_sha256}
    for key in ("source_type", "toolchain", "build_settings"):
        if key in current:
            if current[key] != details[key]:
                return {"matches": False, "artifacts_sha256": artifacts_sha256}
        elif not allow_legacy:
            return {"matches": False, "artifacts_sha256": artifacts_sha256}
    if "built_with" in current and not details["toolchain"].startswith(
        str(current["built_with"])
    ):
        return {"matches": False, "artifacts_sha256": artifacts_sha256}
    if "cmake_flags" in current and current["cmake_flags"] != build_settings.get(
        "cmake_flags"
    ):
        return {"matches": False, "artifacts_sha256": artifacts_sha256}

    stamped_hashes = current.get("artifacts_sha256")
    if isinstance(stamped_hashes, dict):
        if stamped_hashes != artifacts_sha256:
            return {"matches": False, "artifacts_sha256": artifacts_sha256}
    else:
        return {"matches": False, "artifacts_sha256": artifacts_sha256}
    return {
        "matches": True,
        "legacy": any(key not in current for key in (
            "source_type", "toolchain", "build_settings", "artifacts_sha256"
        )),
        "artifacts_sha256": artifacts_sha256,
    }


def parse_manifest_details(
    details: str | None, details_base64: str | None
) -> dict[str, Any] | None:
    if details_base64:
        try:
            details = base64.b64decode(details_base64, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as error:
            fail(f"Invalid base64-encoded manifest component details: {error}")
    if not details:
        return None
    try:
        parsed_details = json.loads(details)
    except json.JSONDecodeError as error:
        fail(f"Invalid manifest component details JSON: {error}")
    if not isinstance(parsed_details, dict):
        fail("Manifest component details must be a JSON object.")
    return parsed_details


def read_manifest_value(output: Path, key: str) -> Any:
    manifest_path = output / ".install-state.json"
    if not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"Cannot read install manifest {manifest_path}: {error}")
    value: Any = manifest
    for part in key.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    checkout_parser = subparsers.add_parser("checkout")
    checkout_parser.add_argument("--repo", required=True)
    checkout_parser.add_argument("--ref", required=True)
    checkout_parser.add_argument("--cache", type=Path, required=True)

    commit_application_parser = subparsers.add_parser("commit-application")
    commit_application_parser.add_argument("--stage", type=Path, required=True)
    commit_application_parser.add_argument("--output", type=Path, required=True)
    commit_application_parser.add_argument("--python", required=True)
    commit_application_parser.add_argument("--source-ref", required=True)
    commit_application_parser.add_argument("--source-commit", default="")
    commit_application_parser.add_argument("--assets-ref", required=True)
    commit_application_parser.add_argument("--assets-commit", required=True)
    commit_application_parser.add_argument(
        "--configure-default-paths", action="store_true"
    )
    commit_application_parser.add_argument("--force-app-files", action="store_true")

    prepare_application_parser = subparsers.add_parser("prepare-application")
    prepare_application_parser.add_argument("--source", type=Path, required=True)
    prepare_application_parser.add_argument("--output", type=Path, required=True)
    prepare_application_parser.add_argument("--python", required=True)
    prepare_application_parser.add_argument("--required-python", required=True)
    prepare_application_parser.add_argument("--supported-api", type=int, required=True)
    prepare_application_parser.add_argument("--assets-repo", required=True)
    prepare_application_parser.add_argument("--assets-ref", required=True)
    prepare_application_parser.add_argument("--reinstall-venv", action="store_true")
    prepare_application_parser.add_argument("--refresh-content", action="store_true")
    prepare_application_parser.add_argument("--reset-config", action="store_true")

    resolve_source_parser = subparsers.add_parser("resolve-source")
    resolve_source_parser.add_argument("--repo")
    resolve_source_parser.add_argument("--source", type=Path)
    resolve_source_parser.add_argument("--ref", required=True)
    resolve_source_parser.add_argument("--cache", type=Path, required=True)
    resolve_source_parser.add_argument("--output", type=Path, required=True)
    resolve_source_parser.add_argument("--supported-api", type=int, required=True)

    settings_parser = subparsers.add_parser("configure-settings")
    settings_parser.add_argument("--config", type=Path, required=True)
    settings_parser.add_argument("--set", dest="assignments", action="append", required=True)

    manifest_get_parser = subparsers.add_parser("manifest-get")
    manifest_get_parser.add_argument("--output", type=Path, required=True)
    manifest_get_parser.add_argument("--key", required=True)

    manifest_operation_parser = subparsers.add_parser("manifest-operation")
    manifest_operation_parser.add_argument("--output", type=Path, required=True)
    manifest_operation_parser.add_argument(
        "--action", choices=("begin", "succeeded", "failed"), required=True
    )
    manifest_operation_parser.add_argument("--error")

    manifest_component_parser = subparsers.add_parser("manifest-component")
    manifest_component_parser.add_argument("--output", type=Path, required=True)
    manifest_component_parser.add_argument("--name", required=True)
    manifest_component_parser.add_argument(
        "--status", choices=("in_progress", "installed", "removed", "failed"), required=True
    )
    details_group = manifest_component_parser.add_mutually_exclusive_group()
    details_group.add_argument("--details")
    details_group.add_argument("--details-base64")
    manifest_component_parser.add_argument("--error")

    install_files_parser = subparsers.add_parser("install-files")
    install_files_parser.add_argument("--file", action="append", required=True)

    projectm_component_parser = subparsers.add_parser("projectm-component")
    projectm_component_parser.add_argument("--output", type=Path, required=True)
    projectm_component_parser.add_argument(
        "--action", choices=("check", "stamp"), required=True
    )
    projectm_component_parser.add_argument("--version", required=True)
    projectm_component_parser.add_argument("--renderer", required=True)
    projectm_component_parser.add_argument("--source-type", required=True)
    projectm_component_parser.add_argument("--ref", required=True)
    projectm_component_parser.add_argument("--commit", default="")
    projectm_component_parser.add_argument("--toolchain", required=True)
    projectm_component_parser.add_argument("--build-settings-base64", required=True)
    projectm_component_parser.add_argument(
        "--artifact", action="append", required=True
    )
    projectm_component_parser.add_argument("--allow-legacy", action="store_true")

    args = parser.parse_args()
    try:
        if args.command == "checkout":
            path, commit_hash, tag = checkout(args.repo, args.ref, args.cache)
            print(json.dumps({"path": str(path), "commit": commit_hash, "tag": tag}))
        elif args.command == "commit-application":
            commit_application(
                args.stage.resolve(),
                args.output.resolve(),
                args.python,
                args.source_ref,
                args.source_commit,
                args.assets_ref,
                args.assets_commit,
                args.configure_default_paths,
                args.force_app_files,
            )
        elif args.command == "prepare-application":
            result = prepare_application(
                args.source,
                args.output,
                args.python,
                args.required_python,
                args.supported_api,
                args.assets_repo,
                args.assets_ref,
                args.reinstall_venv,
                args.refresh_content,
                args.reset_config,
            )
            print(json.dumps(result))
        elif args.command == "resolve-source":
            result = resolve_source(
                args.repo,
                args.source,
                args.ref,
                args.cache,
                args.output,
                args.supported_api,
            )
            print(json.dumps(result))
        elif args.command == "configure-settings":
            settings: dict[str, dict[str, str]] = {}
            for assignment in args.assignments:
                name, separator, value = assignment.partition("=")
                section, section_separator, key = name.partition(".")
                if not separator or not section_separator or not section or not key:
                    fail(f"Invalid setting assignment: {assignment}")
                section_values = settings.setdefault(section, {})
                if key in section_values:
                    fail(f"Duplicate setting assignment: {section}.{key}")
                section_values[key] = value
            set_toml_values(args.config, settings)
        elif args.command == "manifest-get":
            print(json.dumps(read_manifest_value(args.output, args.key)))
        elif args.command == "manifest-operation":
            manifest_operation(args.output, args.action, args.error)
        elif args.command == "manifest-component":
            details = parse_manifest_details(args.details, args.details_base64)
            update_manifest_component(
                args.output, args.name, args.status, details, args.error
            )
        elif args.command == "install-files":
            files: list[tuple[Path, Path]] = []
            for item in args.file:
                source, separator, destination = item.partition("=")
                if not separator or not source or not destination:
                    fail(f"Invalid component file specification: {item}")
                files.append((Path(source), Path(destination)))
            install_files(files)
        elif args.command == "projectm-component":
            build_settings = parse_manifest_details(None, args.build_settings_base64)
            if build_settings is None:
                fail("ProjectM build settings must be a JSON object.")
            artifact_paths: dict[str, Path] = {}
            for item in args.artifact:
                name, separator, raw_path = item.partition("=")
                if not separator or not name or not raw_path:
                    fail(f"Invalid projectM artifact specification: {item}")
                if name in artifact_paths:
                    fail(f"Duplicate projectM artifact name: {name}")
                artifact_paths[name] = Path(raw_path)
            result = projectm_component(
                args.output,
                args.action,
                args.version,
                args.renderer,
                args.source_type,
                args.ref,
                args.commit,
                args.toolchain,
                build_settings,
                artifact_paths,
                args.allow_legacy,
            )
            print(json.dumps(result))
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Installer error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
