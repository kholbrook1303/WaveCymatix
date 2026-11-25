import base64
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1] / "bin"))
import installer_core


class InstallerCoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.output = self.root / "install"
        self.source.mkdir()
        for item in installer_core.APP_ITEMS:
            path = self.source / item
            if item in {"bin", "conf", "docs", "resources", "src"}:
                path.mkdir(parents=True)
                (path / "sample.txt").write_text(item, encoding="utf-8")
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("sample", encoding="utf-8")
        package = self.source / "src" / "wavecymatix"
        (package / "core").mkdir(parents=True)
        (package / "app.py").write_text("def main():\n    return 0\n", encoding="utf-8")
        (package / "VERSION").write_text("1.2.3\n", encoding="utf-8")
        (self.source / "conf" / "settings.toml").write_text(
            '[test]\nvalue = "source"\n', encoding="utf-8"
        )
        (self.source / "VERSION").write_text("INSTALLER_API=1\n", encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def test_platform_installers_use_the_same_ordered_phases(self):
        installer_dir = Path(__file__).parents[1] / "bin"
        for name in ("install-linux.sh", "install-macos.sh", "install-windows.ps1"):
            script = (installer_dir / name).read_text(encoding="utf-8")
            positions = []
            for phase in installer_core.INSTALL_PHASES:
                marker = f"# {phase}"
                self.assertEqual(script.count(marker), 1, f"{name}: expected one {marker}")
                positions.append(script.index(marker))
            self.assertEqual(positions, sorted(positions), f"{name}: phases are out of order")
            self.assertIn("prepare-application", script, f"{name}: app preparation is not shared")
            self.assertIn("commit-application", script, f"{name}: app commit is not shared")
            self.assertIn("configure-settings", script, f"{name}: settings writes are not shared")
            self.assertIn("--configure-default-paths", script)
            self.assertNotIn("presets_custom", script, f"{name}: custom presets are installer-managed")
            self.assertNotIn("textures_custom", script, f"{name}: custom textures are installer-managed")
            self.assertNotRegex(script, r"sed [^\n]*(settings\.toml|config_file)|Set-IniValue")
            self.assertNotRegex(script, r"-m\s+venv|pip install\s+-r")

    def test_release_owned_values_are_not_repeated_in_platform_installers(self):
        installer_dir = Path(__file__).parents[1] / "bin"
        aliases = {
            "INSTALLER_API": (
                "INSTALLER_API",
                "SUPPORTED_INSTALLER_API",
                "SupportedInstallerApi",
            ),
            "APP_REPO": ("APP_REPO",),
            "APP_DEFAULT_REF": ("APP_DEFAULT_REF",),
            "ASSETS_REPO": ("ASSETS_REPO",),
            "ASSETS_DEFAULT_REF": ("ASSETS_DEFAULT_REF",),
            "PROJECTM_REPO": ("PROJECTM_REPO",),
            "PROJECTM_VERSION": ("LIBPROJECTM_VERSION", "ProjectMVersion"),
            "PROJECTM_RENDERER": ("LIBPROJECTM_RENDERER", "PROJECTM_RENDERER"),
            "PROJECTM_CMAKE_FLAGS_LINUX": ("PROJECTM_CMAKE_FLAGS_LINUX",),
            "PROJECTM_CMAKE_FLAGS_MACOS": ("PROJECTM_CMAKE_FLAGS_MACOS",),
            "PROJECTM_CMAKE_FLAGS_WINDOWS": ("PROJECTM_CMAKE_FLAGS_WINDOWS",),
            "PYTHON_VERSION": ("REQUIRED_PYTHON_VERSION",),
            "MIN_CMAKE_VERSION": ("MIN_CMAKE_VERSION",),
            "NODE_VERSION": ("NODE_VERSION",),
            "PLEXAMP_VERSION": ("PLEXAMP_VERSION",),
            "DEJAVU_FONT_VERSION": ("DEJAVU_FONT_VERSION",),
            "DEJAVU_FONT_URL": ("DEJAVU_FONT_URL",),
            "DEJAVU_FONT_SHA256": ("DEJAVU_FONT_SHA256",),
            "LIBERATION_FONT_VERSION": ("LIBERATION_FONT_VERSION",),
            "LIBERATION_FONT_URL": ("LIBERATION_FONT_URL",),
            "VCPKG_REPO": ("VCPKG_REPO",),
            "VCPKG_REF": ("VCPKG_REF",),
            "CMAKE_VERSION": ("CMAKE_VERSION",),
            "BLUEZ_VERSION": ("BLUEZ_VERSION",),
            "SHAIRPORT_SYNC_VERSION": ("SHAIRPORT_SYNC_VERSION",),
            "NQPTP_VERSION": ("NQPTP_VERSION",),
            "SPOTIFYD_VERSION": ("SPOTIFYD_VERSION",),
        }
        config = (installer_dir / "installer.env").read_text(encoding="utf-8")
        for line in config.splitlines():
            if not line or line.startswith("#"):
                continue
            key, value = line.split("=", 1)
            for name in ("install-linux.sh", "install-macos.sh", "install-windows.ps1"):
                script = (installer_dir / name).read_text(encoding="utf-8")
                self.assertIn(key, script, f"{name} does not accept {key}")
            if not value:
                continue
            for name in ("install-linux.sh", "install-macos.sh", "install-windows.ps1"):
                script = (installer_dir / name).read_text(encoding="utf-8")
                for alias in aliases.get(key, ()):
                    if name.endswith(".ps1"):
                        pattern = rf"^\s*\${alias}\s*=\s*['\"]?{re.escape(value)}['\"]?\s*$"
                    else:
                        pattern = rf"^\s*{alias}\s*=['\"]?{re.escape(value)}['\"]?\s*$"
                    self.assertNotRegex(
                        script,
                        pattern,
                        f"{name} duplicates {key}={value} instead of reading installer.env",
                    )

        linux = (installer_dir / "install-linux.sh").read_text(encoding="utf-8")
        for stale_release_value in ("v4.1.8", "v0.4.2", "spotifyd-0.4.2"):
            self.assertNotIn(stale_release_value, linux)

    def test_shared_platform_package_and_plugin_settings_are_consumed(self):
        installer_dir = Path(__file__).parents[1] / "bin"
        windows = (installer_dir / "install-windows.ps1").read_text(encoding="utf-8")
        linux = (installer_dir / "install-linux.sh").read_text(encoding="utf-8")
        for key in (
            "WIN_GIT_PACKAGE_ID",
            "WIN_CMAKE_PACKAGE_ID",
            "WIN_PYTHON_PACKAGE_PREFIX",
            "WIN_FFMPEG_PACKAGE_ID",
            "WIN_VLC_PACKAGE_ID",
            "DEJAVU_FONT_VERSION",
            "DEJAVU_FONT_URL",
            "DEJAVU_FONT_SHA256",
            "LIBERATION_FONT_VERSION",
            "LIBERATION_FONT_URL",
        ):
            self.assertIn(f"'{key}'", windows)
        self.assertIn("$InstallerEnv['WIN_VLC_PACKAGE_ID']", windows)
        self.assertIn("$InstallerEnv['WIN_GIT_PACKAGE_ID']", windows)
        self.assertIn("$InstallerEnv['WIN_PYTHON_PACKAGE_PREFIX']", windows)
        self.assertIn("${PLEXAMP_VERSION}", linux)
        self.assertIn("$NODE_VERSION", linux)
        self.assertIn('MIN_CMAKE_VERSION="$value"', linux)

    def test_platform_installers_delegate_common_app_lifecycle_to_python(self):
        installer_dir = Path(__file__).parents[1] / "bin"
        windows = (installer_dir / "install-windows.ps1").read_text(encoding="utf-8")
        for duplicate_function in (
            "Copy-ProjectFiles",
            "Fetch-VisualAssets",
            "Install-PythonDependencies",
            "Set-IniValue",
        ):
            self.assertNotIn(duplicate_function, windows)

    def test_projectm_reuse_is_automatic_and_skip_switch_is_removed(self):
        installer_dir = Path(__file__).parents[1] / "bin"
        scripts = {
            name: (installer_dir / name).read_text(encoding="utf-8")
            for name in ("install-linux.sh", "install-macos.sh", "install-windows.ps1")
        }
        for name, script in scripts.items():
            self.assertNotIn("SkipProjectMBuild", script, name)
            self.assertNotIn("skip-projectm-build", script, name)
            self.assertIn("projectm-component", script, name)
        linux = scripts["install-linux.sh"]
        macos = scripts["install-macos.sh"]
        windows = scripts["install-windows.ps1"]
        self.assertIn('expected_ref=$(printf \'%s\' "$stamp_ref"', linux)
        self.assertIn('expected_ref=$(printf \'%s\' "$stamp_ref"', macos)
        self.assertIn("$stampRef\n    }\n    else {\n        \"v$ProjectMVersion\"", windows)
        self.assertIn('expected_ref="v$LIBPROJECTM_VERSION"', linux)
        self.assertIn('expected_ref="v$LIBPROJECTM_VERSION"', macos)
        self.assertIn('"v$ProjectMVersion"', windows)
        self.assertIn("Ensure-MSVC\n    Ensure-GlewRuntime", windows)
        self.assertIn("if ($reuse.matches)", windows)

    def test_windows_projectm_reuse_delegates_artifact_and_stamp_checks_to_core(self):
        installer = (
            Path(__file__).parents[1] / "bin" / "install-windows.ps1"
        ).read_text(encoding="utf-8")
        build = installer.split("function Build-ProjectM {", 1)[1].split(
            "\nfunction Get-SourceRepository", 1
        )[0]

        self.assertNotIn("$runtimeDllsExist", build)
        reuse = build.split("if (-not $RebuildProjectM) {", 1)[1].split(
            "Ensure-MSVC", 1
        )[0]
        self.assertIn("Invoke-ProjectMComponent -Action check", reuse)
        self.assertIn("if ($reuse.matches)", reuse)

    def test_linux_does_not_keep_unused_service_or_retry_helpers(self):
        installer = (
            Path(__file__).parents[1] / "bin" / "install-linux.sh"
        ).read_text(encoding="utf-8")

        self.assertNotIn("create_service()", installer)
        self.assertNotIn("retry_function()", installer)

    def test_linux_plugins_without_mode_use_plugin_only_flow(self):
        installer = (
            Path(__file__).parents[1] / "bin" / "install-linux.sh"
        ).read_text(encoding="utf-8")

        self.assertIn('INSTALLATION_MODE_EXPLICIT="false"', installer)
        self.assertIn('INSTALLATION_MODE_EXPLICIT="true"', installer)
        self.assertIn('PLUGIN_ONLY="true"\n    INSTALLATION_MODE="plugins"', installer)
        plugin_only = installer.index('if [ "$PLUGIN_ONLY" = "true" ]; then')
        prerequisites = installer.index("# Phase 2: prerequisites")
        source_resolution = installer.index("# Phase 3: projectM")
        self.assertLess(plugin_only, prerequisites)
        self.assertLess(plugin_only, source_resolution)
        self.assertIn(
            "Plugin-only installation requires an existing WaveCymatix install",
            installer,
        )
        self.assertIn(
            'install_plugin_bluetooth() {\n    # Check if Bluetooth hardware path exists in the Linux kernel\n'
            '    if [ ! -d "/sys/class/bluetooth" ]; then\n'
            '        log "ERROR: No Bluetooth hardware detected at /sys/class/bluetooth"\n'
            "        return 1",
            installer,
        )

    def test_installer_operation_and_profile_options_are_separate(self):
        root = Path(__file__).parents[1]
        linux = (root / "bin" / "install-linux.sh").read_text(encoding="utf-8")
        macos = (root / "bin" / "install-macos.sh").read_text(encoding="utf-8")
        windows = (root / "bin" / "install-windows.ps1").read_text(encoding="utf-8")

        self.assertIn("getopt -o lm:aP:p:s:o:h", linux)
        self.assertIn("-P|--profile)", linux)
        self.assertIn("-P|--profile)", macos)
        self.assertIn("[ValidateSet('install', 'update', 'uninstall')]", windows)
        self.assertNotIn("[Alias('P')]", windows)
        self.assertIn("[string]$Profile", windows)
        for installer in (linux, macos, windows):
            self.assertNotIn("keep-config", installer.lower())
            self.assertNotIn("keepconfig", installer.lower())

        for installer in (linux, macos):
            mode_parser = installer.split("-m|--mode)", 1)[1].split(";;", 1)[0]
            self.assertNotIn("minimal|optimized", mode_parser)
            self.assertIn(
                'case "$INSTALLATION_PROFILE" in minimal|optimized)',
                installer,
            )

        self.assertNotIn(
            "($PSBoundParameters.ContainsKey('Mode') -and $Mode -in @('minimal', 'optimized'))",
            windows,
        )

    def test_linux_bluetooth_installs_and_restarts_matching_obex_daemon(self):
        installer = (
            Path(__file__).parents[1] / "bin" / "install-linux.sh"
        ).read_text(encoding="utf-8")
        bluetooth_setup = installer.split("configure_bluetooth() {", 1)[1].split(
            "\n}\n\ninstall_bluez_for_artwork()", 1
        )[0]
        self.assertLess(
            bluetooth_setup.index("apt install -y pulseaudio-module-bluetooth bluez-tools"),
            bluetooth_setup.index("install_bluez_for_artwork"),
        )
        self.assertIn("systemctl --user restart obex.service", bluetooth_setup)

        bluez_setup = installer.split("install_bluez_for_artwork() {", 1)[1].split(
            "\n}\n\ninstall_plugin_bluetooth()", 1
        )[0]
        self.assertIn("dpkg-query -W -f='${Version}' bluez-obexd", bluez_setup)
        self.assertIn("dpkg --compare-versions", bluez_setup)
        self.assertIn('obexd_stamp="/var/lib/wavecymatix/bluez-obexd-version"', bluez_setup)
        self.assertIn("--enable-obex || return 1", bluez_setup)
        self.assertIn("make install || return 1", bluez_setup)

    def test_linux_restores_install_ownership_after_operations(self):
        installer = (
            Path(__file__).parents[1] / "bin" / "install-linux.sh"
        ).read_text(encoding="utf-8")

        self.assertIn('trap \'manifest_exit_handler "$?" "$BASH_COMMAND"\' EXIT', installer)
        exit_handler = installer.split("manifest_exit_handler() {", 1)[1].split(
            "\nbegin_uninstall_manifest()", 1
        )[0]
        self.assertIn(
            'if [ "$INSTALLATION_PATH_TOUCHED" = "true" ] &&',
            exit_handler,
        )
        self.assertIn(
            'adjust_user_permissions "$INSTALLATION_PATH"',
            exit_handler,
        )
        plugin_only = installer.split('if [ "$PLUGIN_ONLY" = "true" ]; then', 1)[1]
        self.assertLess(
            plugin_only.index('adjust_user_permissions "$INSTALLATION_PATH"'),
            plugin_only.index("record_manifest_operation begin"),
        )
        self.assertIn(
            'chown -R "$SUDO_USER":"$(id -gn "$SUDO_USER")" "$path"',
            installer,
        )

    def test_windows_manifest_details_are_base64_encoded_for_python_cli(self):
        installer = (
            Path(__file__).parents[1] / "bin" / "install-windows.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("'--details-base64'", installer)
        self.assertNotIn("'--details',", installer)

    def test_windows_commit_omits_empty_source_commit_argument(self):
        installer = (
            Path(__file__).parents[1] / "bin" / "install-windows.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("if ($SourceCommit) {", installer)
        self.assertIn("$commitArguments += @('--source-commit', $SourceCommit)", installer)
        self.assertNotIn(
            "'--source-commit', $SourceCommit",
            installer.split("if ($SourceCommit) {", 1)[0],
        )

    def test_macos_installer_trims_crlf_values_from_shared_config(self):
        installer = (
            Path(__file__).parents[1] / "bin" / "install-macos.sh"
        ).read_text(encoding="utf-8")

        self.assertIn('value="${value%%#*}"', installer)
        self.assertIn('value="${value%"${value##*[![:space:]]}"}"', installer)
        self.assertIn('INSTALLER_API) INSTALLER_API="$value" ;;', installer)

    def test_windows_installer_provisions_glew_at_the_application_runtime_path(self):
        installer_dir = Path(__file__).parents[1] / "bin"
        installer = (installer_dir / "install-windows.ps1").read_text(encoding="utf-8")
        rendering = (
            Path(__file__).parents[1]
            / "src"
            / "wavecymatix"
            / "core"
            / "SDLRenderingWindow.py"
        ).read_text(encoding="utf-8")

        self.assertIn("install 'glew:x64-windows'", installer)
        self.assertIn("installed\\x64-windows\\bin\\glew32.dll", installer)
        self.assertIn("Join-Path $RuntimeArtifactsDir 'glew32.dll'", installer)
        self.assertIn("'projectM-4.dll' = Join-Path", installer)
        self.assertIn("'projectM-4-playlist.dll' = Join-Path", installer)
        self.assertIn("'glew32.dll' = Join-Path", installer)
        self.assertIn("'runtime', 'artifacts', 'glew32.dll'", rendering)
        self.assertNotIn("'bin', 'artifacts', 'glew32.dll'", rendering)

    def test_windows_installer_repairs_runtime_artifact_permissions_on_reuse_and_build(self):
        installer = (
            Path(__file__).parents[1] / "bin" / "install-windows.ps1"
        ).read_text(encoding="utf-8")
        repair = installer.split(
            "function Repair-RuntimeArtifactPermissions {", 1
        )[1].split("\n}\n", 1)[0]

        for argument in ("'/reset'", "'/T'", "'/C'", "'/Q'"):
            self.assertIn(argument, repair)
        self.assertIn("if ($LASTEXITCODE -ne 0)", repair)
        build = installer.split("function Build-ProjectM {", 1)[1].split(
            "\nfunction Get-SourceRepository", 1
        )[0]
        self.assertEqual(build.count("Repair-RuntimeArtifactPermissions"), 2)

    def test_local_source_must_be_outside_install(self):
        self.output.mkdir()
        package = self.output / "src" / "wavecymatix"
        (package / "core").mkdir(parents=True)
        (package / "app.py").write_text("", encoding="utf-8")
        (self.output / "pyproject.toml").write_text("", encoding="utf-8")
        (self.output / "VERSION").write_text(
            "INSTALLER_API=1\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(RuntimeError, "must not be the same as or inside"):
            installer_core.validate_source(self.output, self.output)

    def test_resolve_source_validates_local_source_and_returns_metadata(self):
        resolved = installer_core.resolve_source(
            None,
            self.source,
            "local",
            self.root / "cache",
            self.output,
            supported_api=1,
        )

        self.assertEqual(resolved["path"], str(self.source.resolve()))
        self.assertEqual(resolved["ref"], "local")
        self.assertEqual(resolved["commit"], "")

    def test_resolve_source_rejects_source_with_unsupported_installer_api(self):
        (self.source / "VERSION").write_text(
            "INSTALLER_API=2\n", encoding="utf-8"
        )

        with self.assertRaisesRegex(RuntimeError, "requires installer API 2"):
            installer_core.resolve_source(
                None,
                self.source,
                "local",
                self.root / "cache",
                self.output,
                supported_api=1,
            )

    def test_application_version_is_read_from_package_version_file(self):
        version_file = self.source / "src" / "wavecymatix" / "VERSION"
        self.assertEqual(installer_core.read_app_version(version_file), "1.2.3")
        self.assertEqual(
            installer_core.read_version(self.source / "VERSION"),
            {"INSTALLER_API": "1"},
        )

    def test_resolve_source_reports_remote_ref_without_required_application_files(self):
        incomplete_source = self.root / "incomplete-source"
        incomplete_source.mkdir()
        (incomplete_source / "README.md").write_text("not the application", encoding="utf-8")

        with mock.patch.object(
            installer_core,
            "checkout",
            return_value=(incomplete_source, "commit", ""),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                r"missing required paths: VERSION, pyproject\.toml, src/wavecymatix/app\.py.*-LocalInstall or -Source",
            ):
                installer_core.resolve_source(
                    "https://example.invalid/WaveCymatix.git",
                    None,
                    "main",
                    self.root / "cache",
                    self.output,
                    supported_api=1,
                )

    def test_prepare_content_stages_only_when_content_is_not_current(self):
        assets = self.root / "assets"
        with (
            mock.patch.object(
                installer_core,
                "checkout",
                return_value=(assets, "assets-commit", "v1"),
            ),
            mock.patch.object(installer_core, "content_is_current", return_value=False),
            mock.patch.object(installer_core, "stage_content") as stage_content,
        ):
            result = installer_core.prepare_content(
                "https://example.invalid/assets.git",
                "v1",
                self.root / "cache",
                self.output,
            )

        stage_content.assert_called_once_with(assets, self.output)
        self.assertEqual(result["path"], str(assets))
        self.assertEqual(result["commit"], "assets-commit")
        self.assertEqual(result["ref"], "v1")
        self.assertFalse(result["current"])
        self.assertTrue(result["staged"])
        manifest = json.loads(
            (self.output / ".install-state.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            manifest["components"]["visual-assets"]["status"], "in_progress"
        )

    def test_prepare_application_owns_shared_staging_content_and_python_setup(self):
        (self.output / "conf").mkdir(parents=True)
        (self.output / "conf" / "settings.toml").write_text(
            '[general]\nvalue = "user"\n', encoding="utf-8"
        )
        installer_core.manifest_operation(self.output, "begin")
        python_path = installer_core._venv_python(self.output / ".venv")
        content = {
            "path": str(self.root / "assets"),
            "ref": "assets-v1",
            "commit": "assets-commit",
            "staged": False,
        }

        def fake_run_python(python, arguments):
            if arguments[:2] == ["-m", "venv"]:
                python_path.parent.mkdir(parents=True, exist_ok=True)
                python_path.write_text("", encoding="utf-8")

        with (
            mock.patch.object(installer_core, "prepare_content", return_value=content),
            mock.patch.object(installer_core, "_run_python", side_effect=fake_run_python),
            mock.patch.object(installer_core, "_python_version", return_value="3.12"),
            mock.patch.object(
                installer_core, "_full_python_version", return_value="3.12.1"
            ),
        ):
            result = installer_core.prepare_application(
                self.source,
                self.output,
                "system-python",
                "3.12",
                1,
                "https://example.invalid/assets.git",
                "main",
            )

        self.assertTrue(Path(result["stage_dir"]).is_dir())
        self.assertEqual(result["venv_path"], str(self.output / ".venv"))
        self.assertEqual(result["venv_python"], str(python_path))
        self.assertEqual(result["assets_commit"], "assets-commit")
        self.assertEqual(result["assets_ref"], "assets-v1")
        self.assertTrue(result["had_user_config"])
        self.assertEqual(
            (Path(result["stage_dir"]) / "conf" / "settings.toml").read_text(
                encoding="utf-8"
            ),
            '[general]\nvalue = "user"\n\n[test]\nvalue = "source"\n',
        )
        manifest = json.loads(
            (self.output / ".install-state.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["components"]["python"]["version"], "3.12.1")
        self.assertNotEqual(
            manifest["components"]["application"]["status"], "in_progress"
        )
        self.assertTrue((self.output / "data").is_dir())

    def test_prepare_application_uses_dot_venv_instead_of_legacy_environment(self):
        installer_core.manifest_operation(self.output, "begin")
        installer_core.update_manifest_component(
            self.output,
            "python",
            "installed",
            {"requirements_sha256": "same-digest"},
        )
        legacy_python = installer_core._venv_python(self.output / "venv")
        legacy_python.parent.mkdir(parents=True)
        legacy_python.write_text("legacy-python", encoding="utf-8")
        content = {
            "path": str(self.root / "assets"),
            "ref": "assets-v1",
            "commit": "assets-commit",
            "staged": False,
        }
        created_python = installer_core._venv_python(self.output / ".venv")
        python_calls = []

        def fake_run_python(python, arguments):
            python_calls.append((python, arguments))
            if arguments[:2] == ["-m", "venv"]:
                created_python.parent.mkdir(parents=True, exist_ok=True)
                created_python.write_text("", encoding="utf-8")

        with (
            mock.patch.object(installer_core, "prepare_content", return_value=content),
            mock.patch.object(installer_core, "_run_python", side_effect=fake_run_python),
            mock.patch.object(installer_core, "_python_version", return_value="3.12"),
            mock.patch.object(
                installer_core, "_full_python_version", return_value="3.12.1"
            ),
            mock.patch.object(installer_core, "requirements_hash", return_value="same-digest"),
        ):
            result = installer_core.prepare_application(
                self.source,
                self.output,
                "system-python",
                "3.12",
                1,
                "https://example.invalid/assets.git",
                "main",
            )

        self.assertEqual(result["venv_path"], str(self.output / ".venv"))
        self.assertEqual(result["venv_python"], str(created_python))
        self.assertTrue(legacy_python.is_file())
        self.assertIn(
            (
                str(created_python),
                ["-m", "pip", "install", "-r", str(Path(result["stage_dir"]) / "requirements.txt")],
            ),
            python_calls,
        )

    def test_stage_and_commit_preserve_user_state_and_runtime(self):
        self.output.mkdir()
        (self.output / "conf").mkdir()
        (self.output / "conf" / "settings.toml").write_text(
            '[user]\nvalue = "kept"\n', encoding="utf-8"
        )
        (self.output / "data").mkdir()
        (self.output / "data" / "playlist.db").write_text("data", encoding="utf-8")
        (self.output / "runtime" / "artifacts").mkdir(parents=True)
        (self.output / "runtime" / "artifacts" / "projectM-4.dll").write_text("dll", encoding="utf-8")

        staged = installer_core.stage(self.source, self.output)
        self.assertIn('value = "kept"', (staged / "conf" / "settings.toml").read_text(encoding="utf-8"))
        installer_core.commit(self.output)

        self.assertFalse((self.output / "WaveCymatix.py").exists())
        self.assertIn(
            'value = "kept"',
            (self.output / "conf" / "settings.toml").read_text(encoding="utf-8"),
        )
        self.assertEqual((self.output / "data" / "playlist.db").read_text(encoding="utf-8"), "data")
        self.assertEqual(
            (self.output / "runtime" / "artifacts" / "projectM-4.dll").read_text(encoding="utf-8"),
            "dll",
        )
        self.assertIn('value = "kept"', (self.output / "conf" / "settings.toml").read_text(encoding="utf-8"))

    def test_application_stages_and_installs_without_development_tools(self):
        tools = self.source / "tools"
        if tools.exists():
            (tools / "sample.txt").unlink()
            tools.rmdir()

        staged = installer_core.stage(self.source, self.output)
        self.assertFalse((staged / "tools").exists())
        installer_core.commit(self.output)
        self.assertFalse((self.output / "tools").exists())

    def test_application_does_not_ship_development_tools_when_present(self):
        tools = self.source / "tools"
        tools.mkdir(exist_ok=True)
        (tools / "development.py").write_text("", encoding="utf-8")

        staged = installer_core.stage(self.source, self.output)
        self.assertFalse((staged / "tools").exists())
        installer_core.commit(self.output)
        self.assertFalse((self.output / "tools").exists())

    def test_application_update_preserves_existing_tools_directory(self):
        tools = self.output / "tools"
        tools.mkdir(parents=True)
        (tools / "personal.txt").write_text("keep", encoding="utf-8")

        installer_core.stage(self.source, self.output)
        installer_core.commit(self.output)
        self.assertEqual((tools / "personal.txt").read_text(encoding="utf-8"), "keep")

    def test_stage_adds_missing_toml_defaults_without_overwriting_user_values(self):
        defaults = self.source / "conf"
        (defaults / "settings.toml").write_text(
            "[general]\n"
            "log_level = 20\n"
            "# New feature option for users\n"
            'new_option = "shipped"\n'
            "\n[feature]\n"
            "enabled = true\n",
            encoding="utf-8",
        )
        (defaults / "audio_cards.toml").write_text(
            "[general]\naudio_cards = []\n", encoding="utf-8"
        )
        (self.output / "conf").mkdir(parents=True)
        (self.output / "conf" / "settings.toml").write_text(
            '[general]\n# Keep this user comment\nlog_level = 10\n'
            'user_option = "custom"\n',
            encoding="utf-8",
        )

        staged = installer_core.stage(self.source, self.output)
        settings_path = staged / "conf" / "settings.toml"
        settings_text = settings_path.read_text(encoding="utf-8")
        settings = installer_core.tomllib.loads(settings_text)

        self.assertEqual(settings["general"]["log_level"], 10)
        self.assertEqual(settings["general"]["new_option"], "shipped")
        self.assertEqual(settings["general"]["user_option"], "custom")
        self.assertTrue(settings["feature"]["enabled"])
        self.assertIn("# Keep this user comment", settings_text)
        self.assertIn("# New feature option for users", settings_text)
        self.assertEqual(
            installer_core.tomllib.loads(
                (staged / "conf" / "audio_cards.toml").read_text(encoding="utf-8")
            )["general"]["audio_cards"],
            [],
        )
        merged_text = settings_path.read_text(encoding="utf-8")
        installer_core.merge_toml_config_defaults(defaults, staged / "conf")
        self.assertEqual(settings_path.read_text(encoding="utf-8"), merged_text)

    def test_commit_application_skips_file_swap_for_unchanged_clean_source(self):
        (self.output / "conf").mkdir(parents=True)
        settings = self.source / "conf" / "settings.toml"
        settings.write_text(
            "[projectm]\n"
            f'"projectM.presetPath.1" = {json.dumps(str(self.output / "presets"))}\n'
            f'"projectM.presetPath.2" = {json.dumps(str(self.output / "presets_custom"))}\n'
            f'"projectM.texturePath.1" = {json.dumps(str(self.output / "textures"))}\n'
            f'"projectM.texturePath.2" = {json.dumps(str(self.output / "sprites"))}\n'
            f'"projectM.texturePath.3" = {json.dumps(str(self.output / "textures_custom"))}\n',
            encoding="utf-8",
        )
        (self.output / "conf" / "settings.toml").write_text(
            settings.read_text(encoding="utf-8"), encoding="utf-8"
        )
        (self.output / "WaveCymatix.py").write_text("installed-version", encoding="utf-8")
        (self.output / "requirements.txt").write_text(
            (self.source / "requirements.txt").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        (self.output / "VERSION").write_text(
            (self.source / "VERSION").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        (self.output / ".prev").mkdir()
        (self.output / ".prev" / "marker").write_text("keep", encoding="utf-8")
        installer_core.update_manifest_component(
            self.output,
            "application",
            "installed",
            {"version": "1.2.3", "ref": "main", "commit": "same-commit"},
        )
        staged = installer_core.stage(self.source, self.output)

        with mock.patch.object(installer_core, "validate"):
            installer_core.commit_application(
                staged,
                self.output,
                sys.executable,
                "main",
                "same-commit",
                "main",
                "assets-commit",
            )

        self.assertFalse((self.output / "WaveCymatix.py").exists())
        self.assertEqual(
            (self.output / ".app-prev" / "WaveCymatix.py").read_text(encoding="utf-8"),
            "installed-version",
        )
        self.assertEqual(
            (self.output / ".prev" / "marker").read_text(encoding="utf-8"),
            "keep",
        )
        self.assertFalse((self.output / ".new").exists())

    def test_commit_application_replaces_files_for_changed_inputs_or_local_source(self):
        cases = (
            ("source", "new-commit", False),
            ("requirements", "same-commit", False),
            ("config", "same-commit", False),
            ("local", "same-commit", True),
        )
        for name, commit, force in cases:
            with self.subTest(case=name):
                output = self.root / f"install-{name}"
                (output / "conf").mkdir(parents=True)
                config = output / "conf" / "settings.toml"
                config.write_text("[projectm]\n", encoding="utf-8")
                installer_core.ensure_install_paths(config, output)
                (output / "WaveCymatix.py").write_text(
                    "installed-version", encoding="utf-8"
                )
                (output / "requirements.txt").write_text(
                    (self.source / "requirements.txt").read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
                if name == "requirements":
                    (output / "requirements.txt").write_text(
                        "changed-requirement\n", encoding="utf-8"
                    )
                (output / "VERSION").write_text(
                    (self.source / "VERSION").read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
                installer_core.update_manifest_component(
                    output,
                    "application",
                    "installed",
                    {"version": "1.2.3", "ref": "main", "commit": "same-commit"},
                )
                staged = installer_core.stage(self.source, output)
                if name == "config":
                    with (staged / "conf" / "settings.toml").open(
                        "a", encoding="utf-8"
                    ) as staged_config:
                        staged_config.write("new-default=true\n")

                with mock.patch.object(installer_core, "validate"):
                    installer_core.commit_application(
                        staged,
                        output,
                        sys.executable,
                        "main",
                        commit,
                        "main",
                        "assets-commit",
                        force_app_files=force,
                    )

                self.assertFalse((output / "WaveCymatix.py").exists())

    def test_failed_install_restores_config_and_content_not_application_files(self):
        (self.output / "conf").mkdir(parents=True)
        (self.output / "conf" / "settings.toml").write_text(
            "[projectm]\n", encoding="utf-8"
        )
        (self.output / "presets").mkdir()
        (self.output / "presets" / "old.milk").write_text("old preset", encoding="utf-8")
        (self.output / "WaveCymatix.py").write_text("old-app", encoding="utf-8")
        (self.output / "requirements.txt").write_text("old-requirements\n", encoding="utf-8")
        (self.output / "VERSION").write_text(
            "INSTALLER_API=1\n", encoding="utf-8"
        )
        installer_core.update_manifest_component(
            self.output,
            "application",
            "installed",
            {"version": "1.0.0", "ref": "main", "commit": "old-commit"},
        )
        installer_core.update_manifest_component(
            self.output,
            "visual-assets",
            "installed",
            {"ref": "main", "commit": "old-assets"},
        )
        installer_core.manifest_operation(self.output, "begin")
        staged = installer_core.stage(self.source, self.output)
        assets_source = self.root / "assets-source"
        for item in installer_core.CONTENT_ITEMS:
            (assets_source / item).mkdir(parents=True, exist_ok=True)
            (assets_source / item / "new.milk").write_text(
                "new preset", encoding="utf-8"
            )
        installer_core.stage_content(assets_source, self.output)

        with mock.patch.object(installer_core, "validate"):
            installer_core.commit_application(
                staged,
                self.output,
                sys.executable,
                "main",
                "new-commit",
                "main",
                "new-assets",
            )

        self.assertFalse((self.output / "WaveCymatix.py").exists())
        self.assertFalse((self.output / "presets" / "old.milk").exists())
        installer_core.manifest_operation(
            self.output, "failed", "injected downstream failure"
        )

        self.assertEqual(
            (self.output / "WaveCymatix.py").read_text(encoding="utf-8"),
            "old-app",
        )
        self.assertEqual(
            (self.output / "conf" / "settings.toml").read_text(encoding="utf-8"),
            "[projectm]\n",
        )
        self.assertEqual(
            (self.output / "presets" / "old.milk").read_text(encoding="utf-8"),
            "old preset",
        )
        manifest = json.loads(
            (self.output / ".install-state.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            manifest["components"]["application"]["status"], "installed"
        )
        self.assertEqual(
            manifest["components"]["application"]["commit"], "new-commit"
        )
        self.assertEqual(
            manifest["components"]["visual-assets"]["commit"], "old-assets"
        )
        self.assertFalse((self.output / ".installer-app-rollback.json").exists())

    def test_failed_install_does_not_restore_modified_python_environment(self):
        environment = self.output / ".venv"
        python = environment / "bin" / "python"
        python.parent.mkdir(parents=True)
        python.write_text("old-python", encoding="utf-8")
        installer_core.manifest_operation(self.output, "begin")
        installer_core.update_manifest_component(
            self.output, "python", "in_progress"
        )
        python.write_text("partially-updated-python", encoding="utf-8")
        (environment / "partial-package").write_text("partial", encoding="utf-8")

        installer_core.manifest_operation(
            self.output, "failed", "injected dependency failure"
        )

        self.assertEqual(python.read_text(encoding="utf-8"), "partially-updated-python")
        self.assertTrue((environment / "partial-package").exists())

    def test_failed_install_leaves_new_partial_python_environment_for_reinstall(self):
        environment = self.output / ".venv"
        installer_core.manifest_operation(self.output, "begin")
        installer_core.update_manifest_component(
            self.output, "python", "in_progress"
        )
        (environment / "partial-package").mkdir(parents=True)

        installer_core.manifest_operation(
            self.output, "failed", "injected environment creation failure"
        )

        self.assertTrue(environment.exists())
        manifest = json.loads(
            (self.output / ".install-state.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["components"]["python"]["status"], "failed")

    def test_failed_component_update_does_not_claim_previous_version(self):
        installer_core.update_manifest_component(
            self.output,
            "projectm",
            "installed",
            {"version": "4.1.8", "ref": "v4.1.8", "commit": "old-commit"},
        )
        installer_core.update_manifest_component(
            self.output, "projectm", "in_progress"
        )
        installer_core.update_manifest_component(
            self.output, "projectm", "failed", error="build failed"
        )

        manifest = json.loads(
            (self.output / ".install-state.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["components"]["projectm"]["status"], "failed")
        self.assertNotIn("version", manifest["components"]["projectm"])

    def test_failed_component_operation_does_not_claim_previous_version(self):
        installer_core.update_manifest_component(
            self.output,
            "plugin-spotifyd",
            "installed",
            {"version": "1.2.3", "path": "/usr/local/bin/spotifyd"},
        )
        installer_core.manifest_operation(self.output, "begin")
        installer_core.update_manifest_component(
            self.output, "plugin-spotifyd", "in_progress"
        )
        installer_core.manifest_operation(self.output, "failed", "replacement failed")

        manifest = json.loads(
            (self.output / ".install-state.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            manifest["components"]["plugin-spotifyd"]["status"], "failed"
        )
        self.assertNotIn("version", manifest["components"]["plugin-spotifyd"])

    def test_install_files_does_not_back_up_component_files_on_failure(self):
        sources = [self.root / "new-a", self.root / "new-b"]
        destinations = [self.root / "install-a", self.root / "install-b"]
        for source, destination, old_value, new_value in zip(
            sources, destinations, ("old-a", "old-b"), ("new-a", "new-b")
        ):
            source.write_text(new_value, encoding="utf-8")
            destination.write_text(old_value, encoding="utf-8")

        replace = os.replace
        call_count = 0

        def fail_second_install(source, destination):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise OSError("injected replacement failure")
            replace(source, destination)

        with mock.patch.object(installer_core.os, "replace", side_effect=fail_second_install):
            with self.assertRaisesRegex(OSError, "injected replacement failure"):
                installer_core.install_files(list(zip(sources, destinations)))

        self.assertEqual(destinations[0].read_text(encoding="utf-8"), "new-a")
        self.assertEqual(destinations[1].read_text(encoding="utf-8"), "old-b")

    def test_install_files_leaves_partial_first_install_for_reinstall(self):
        sources = [self.root / "new-a", self.root / "new-b"]
        destinations = [self.root / "fresh-a", self.root / "fresh-b"]
        for source, value in zip(sources, ("new-a", "new-b")):
            source.write_text(value, encoding="utf-8")

        replace = os.replace
        call_count = 0

        def fail_second_install(source, destination):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise OSError("injected replacement failure")
            replace(source, destination)

        with mock.patch.object(installer_core.os, "replace", side_effect=fail_second_install):
            with self.assertRaisesRegex(OSError, "injected replacement failure"):
                installer_core.install_files(list(zip(sources, destinations)))

        self.assertEqual(destinations[0].read_text(encoding="utf-8"), "new-a")
        self.assertFalse(destinations[1].exists())

    def test_install_files_cli_promotes_the_requested_file(self):
        source = self.root / "staged-file"
        destination = self.root / "installed-file"
        source.write_text("component", encoding="utf-8")
        with mock.patch.object(
            sys,
            "argv",
            [
                "installer_core.py",
                "install-files",
                "--file",
                f"{source}={destination}",
            ],
        ):
            self.assertEqual(installer_core.main(), 0)
        self.assertEqual(destination.read_text(encoding="utf-8"), "component")

    def test_commit_application_runs_configure_validate_and_swap_in_order(self):
        stage = self.root / "stage"
        stage.mkdir()
        (stage / "VERSION").write_text(
            "INSTALLER_API=1\n", encoding="utf-8"
        )
        package_version = stage / "src" / "wavecymatix" / "VERSION"
        package_version.parent.mkdir(parents=True)
        package_version.write_text("1.2.3\n", encoding="utf-8")
        calls = []

        with (
            mock.patch.object(
                installer_core,
                "ensure_install_paths",
                side_effect=lambda config, output, configure_default_paths: calls.append(
                    ("config", config, output, configure_default_paths)
                ),
            ),
            mock.patch.object(
                installer_core,
                "validate",
                side_effect=lambda stage_dir, python: calls.append(("validate", stage_dir, python)),
            ),
            mock.patch.object(
                installer_core,
                "commit",
                side_effect=lambda output, **kwargs: calls.append(
                    ("commit", output, kwargs)
                ),
            ),
        ):
            self.output.mkdir()
            (self.output / "VERSION").write_text(
                "INSTALLER_API=1\n", encoding="utf-8"
            )
            installer_core.manifest_operation(self.output, "begin")
            installer_core.commit_application(
                stage,
                self.output,
                "python-test",
                "v1.2.3",
                "source-commit",
                "assets-v1",
                "assets-commit",
            )

        self.assertEqual(
            [call[0] for call in calls],
            ["config", "validate", "commit"],
        )
        self.assertEqual(calls[0][1], stage / "conf" / "settings.toml")
        self.assertFalse(calls[0][3])
        self.assertEqual(calls[1], ("validate", stage, "python-test"))
        self.assertEqual(
            calls[2],
            ("commit", self.output, {"mark_application_in_progress": True}),
        )
        manifest = json.loads(
            (self.output / ".install-state.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            manifest["components"]["application"]["commit"], "source-commit"
        )
        self.assertEqual(
            manifest["components"]["visual-assets"]["commit"], "assets-commit"
        )

    def test_commit_application_cli_accepts_omitted_optional_source_commit(self):
        with (
            mock.patch.object(
                sys,
                "argv",
                [
                    "installer_core.py",
                    "commit-application",
                    "--stage",
                    str(self.root / "stage"),
                    "--output",
                    str(self.output),
                    "--python",
                    "python-test",
                    "--source-ref",
                    "local",
                    "--assets-ref",
                    "main",
                    "--assets-commit",
                    "assets-commit",
                ],
            ),
            mock.patch.object(installer_core, "commit_application") as commit_application,
        ):
            self.assertEqual(installer_core.main(), 0)

        self.assertEqual(commit_application.call_args.args[4], "")

    def test_commit_does_not_restore_application_files_after_swap_failure(self):
        self.output.mkdir()
        (self.output / "assets").mkdir()
        (self.output / "assets" / "sample.txt").write_text("old", encoding="utf-8")
        installer_core.stage(self.source, self.output)
        original_replace = installer_core.os.replace
        calls = 0

        def fail_second_replace(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected replace failure")
            return original_replace(source, destination)

        with mock.patch.object(installer_core.os, "replace", side_effect=fail_second_replace):
            with self.assertRaisesRegex(OSError, "injected"):
                installer_core.commit(self.output)

        self.assertEqual(
            (self.output / "assets" / "sample.txt").read_text(encoding="utf-8"),
            "old",
        )

    def test_commit_removes_previous_backup_with_readonly_files(self):
        installer_core.stage(self.source, self.output)
        readonly_file = (
            self.output / ".prev" / "bin" / "third_party" / "vcpkg" / ".git" / "objects" / "pack"
            / "pack.idx"
        )
        readonly_file.parent.mkdir(parents=True)
        readonly_file.write_text("stale backup", encoding="utf-8")
        os.chmod(readonly_file, stat.S_IREAD)

        installer_core.commit(self.output)
        installer_core.discard_install_backups(self.output)

        self.assertFalse((self.output / ".prev" / "bin").exists())
        self.assertFalse((self.output / "WaveCymatix.py").exists())

    def test_content_current_requires_matching_stamp_and_content(self):
        self.output.mkdir()
        for item in installer_core.CONTENT_ITEMS:
            (self.output / item).mkdir()
        self.assertFalse(installer_core.content_is_current(self.output, "assets-commit"))

        (self.output / ".install-state.json").write_text(
            json.dumps({"content": {"visual_assets_commit": "assets-commit"}}),
            encoding="utf-8",
        )
        self.assertTrue(installer_core.content_is_current(self.output, "assets-commit"))
        self.assertFalse(
            installer_core.content_is_current(self.output, "assets-commit", force=True)
        )
        (self.output / "sprites").rmdir()
        self.assertFalse(installer_core.content_is_current(self.output, "assets-commit"))

    def test_ensure_install_paths_preserves_user_values_and_is_idempotent(self):
        config = self.output / "conf" / "settings.toml"
        config.parent.mkdir(parents=True)
        config.write_text(
            "[projectm]\n"
            '"projectM.presetPath" = "/user/presets"\n'
            '"projectM.presetPath.1" = "/custom/presets"\n'
            '"projectM.texturePath" = "/user/textures"\n'
            '"projectM.texturePath.1" = "/user/sprites"\n'
            '"projectM.texturePath.2" = "/custom/textures"\n'
            '#"projectM.texturePath.3" = "/commented/path"\n'
            '\n[other]\nvalue = "kept"\n',
            encoding="utf-8",
        )

        installer_core.ensure_install_paths(config, self.output)
        configured = config.read_text(encoding="utf-8")
        for name in (
            "presets",
            "textures",
            "sprites",
        ):
            self.assertIn(json.dumps(str(self.output / name)), configured)
        self.assertNotIn(json.dumps(str(self.output / "presets_custom")), configured)
        self.assertNotIn(json.dumps(str(self.output / "textures_custom")), configured)
        self.assertIn('"projectM.presetPath" = "/user/presets"', configured)
        self.assertIn('"projectM.presetPath.1" = "/custom/presets"', configured)
        self.assertIn('"projectM.texturePath.2" = "/custom/textures"', configured)
        self.assertIn('#"projectM.texturePath.3" = "/commented/path"', configured)
        self.assertIn('[other]\nvalue = "kept"', configured)
        parsed = installer_core.tomllib.loads(configured)
        self.assertEqual(
            parsed["projectm"]["projectM.presetPath.1"],
            "/custom/presets",
        )

        installer_core.ensure_install_paths(config, self.output)
        self.assertEqual(config.read_text(encoding="utf-8"), configured)

    def test_ensure_install_paths_replaces_shipped_paths_in_place(self):
        config = self.output / "conf" / "settings.toml"
        config.parent.mkdir(parents=True)
        config.write_text(
            "[projectm]\n"
            '"projectM.presetPath" = "/opt/WaveCymatix/presets"\n'
            '"projectM.texturePath" = "/opt/WaveCymatix/textures"\n'
            '"projectM.texturePath.1" = "/opt/WaveCymatix/sprites"\n'
            '\n[other]\nvalue = "kept"\n',
            encoding="utf-8",
        )

        installer_core.ensure_install_paths(config, self.output)

        configured = config.read_text(encoding="utf-8")
        self.assertIn(
            f'"projectM.presetPath" = {json.dumps(str(self.output / "presets"))}',
            configured,
        )
        self.assertIn(
            f'"projectM.texturePath" = {json.dumps(str(self.output / "textures"))}',
            configured,
        )
        self.assertIn(
            f'"projectM.texturePath.1" = {json.dumps(str(self.output / "sprites"))}',
            configured,
        )
        self.assertNotIn("/opt/WaveCymatix/", configured)
        self.assertNotIn('"projectM.presetPath.1"', configured)
        self.assertNotIn('"projectM.texturePath.2"', configured)
        self.assertIn('[other]\nvalue = "kept"', configured)

        installer_core.ensure_install_paths(config, self.output)
        self.assertEqual(config.read_text(encoding="utf-8"), configured)

    def test_set_toml_values_updates_only_target_table_and_preserves_comments(self):
        config = self.output / "settings.toml"
        self.output.mkdir()
        config.write_text(
            '[monitors]\naudio = true\n#display = true\n'
            '\n[other]\naudio = "untouched"\n',
            encoding="utf-8",
        )

        installer_core.set_toml_values(
            config,
            {"monitors": {"audio": "False", "display": "False"}},
        )

        configured = config.read_text(encoding="utf-8")
        monitors = configured.split("[other]", 1)[0]
        self.assertIn("audio = false", monitors)
        self.assertIn("#display = true", monitors)
        self.assertIn("display = false", monitors)
        self.assertIn('[other]\naudio = "untouched"', configured)
        parsed = installer_core.tomllib.loads(configured)
        self.assertIs(parsed["monitors"]["audio"], False)

    def test_configure_settings_cli_applies_assignments(self):
        config = self.output / "settings.toml"
        self.output.mkdir()
        config.write_text('[projectm]\n"window.fullscreen" = false\n', encoding="utf-8")

        with mock.patch.object(
            sys,
            "argv",
            [
                "installer_core.py",
                "configure-settings",
                "--config",
                str(config),
                "--set",
                "projectm.window.fullscreen=true",
            ],
        ):
            self.assertEqual(installer_core.main(), 0)

        parsed = installer_core.tomllib.loads(config.read_text(encoding="utf-8"))
        self.assertIs(parsed["projectm"]["window.fullscreen"], True)

    def test_ensure_install_paths_configures_new_install_paths(self):
        config = self.output / "settings.toml"
        self.output.mkdir()
        config.write_text(
            '[general]\nplaylistDbPath = "/old/data.db"\n'
            '[projectm]\n"projectM.presetDeleteBackupPath" = "/old/backup"\n',
            encoding="utf-8",
        )

        installer_core.ensure_install_paths(config, self.output, True)

        configured = config.read_text(encoding="utf-8")
        self.assertIn(
            f'playlistDbPath = {json.dumps(str(self.output / "data" / "media_library.db"))}',
            configured,
        )
        self.assertIn(
            f'"projectM.presetDeleteBackupPath" = {json.dumps(str(self.output / "preset_backup"))}',
            configured,
        )

    def test_ensure_install_paths_preserves_existing_user_data_paths(self):
        config = self.output / "settings.toml"
        self.output.mkdir()
        config.write_text(
            '[general]\nplaylistDbPath = "/user/media.db"\n'
            '[projectm]\n"projectM.presetDeleteBackupPath" = "/user/backup"\n',
            encoding="utf-8",
        )

        installer_core.ensure_install_paths(config, self.output)

        configured = config.read_text(encoding="utf-8")
        self.assertIn('playlistDbPath = "/user/media.db"', configured)
        self.assertIn('"projectM.presetDeleteBackupPath" = "/user/backup"', configured)

    def test_ensure_install_paths_handles_windows_paths(self):
        config = self.output / "settings.toml"
        self.output.mkdir()
        config.write_text(
            '[projectm]\n"projectM.presetPath" = "C:\\\\old\\\\presets"\n',
            encoding="utf-8",
        )

        installer_core.ensure_install_paths(config, self.output)

        configured = config.read_text(encoding="utf-8")
        self.assertIn(
            f'"projectM.presetPath" = {json.dumps("C:\\old\\presets")}',
            configured,
        )
        self.assertIn(json.dumps(str(self.output.resolve() / "presets")), configured)
        self.assertNotIn(
            json.dumps(str(self.output.resolve() / "presets_custom")), configured
        )

    def test_commit_swaps_app_and_content_together(self):
        assets = self.root / "assets-source"
        for item in installer_core.CONTENT_ITEMS:
            (assets / item).mkdir(parents=True)
            (assets / item / "current.milk").write_text("new", encoding="utf-8")
            (self.output / item).mkdir(parents=True)
            (self.output / item / "stale.milk").write_text("old", encoding="utf-8")

        installer_core.stage(self.source, self.output)
        installer_core.stage_content(assets, self.output)
        installer_core.commit(self.output)

        self.assertFalse((self.output / "WaveCymatix.py").exists())
        self.assertTrue((self.output / "presets" / "current.milk").is_file())
        self.assertFalse((self.output / "presets" / "stale.milk").exists())
        self.assertTrue((self.output / ".content-prev" / "presets" / "stale.milk").is_file())

    def test_commit_rolls_back_content_when_content_swap_fails(self):
        assets = self.root / "assets-source"
        for item in installer_core.CONTENT_ITEMS:
            (assets / item).mkdir(parents=True)
            (assets / item / "current.milk").write_text("new", encoding="utf-8")
            (self.output / item).mkdir(parents=True)
            (self.output / item / "stale.milk").write_text("old", encoding="utf-8")
        (self.output / "assets").mkdir(parents=True)
        (self.output / "assets" / "sample.txt").write_text("old-app", encoding="utf-8")
        installer_core.stage(self.source, self.output)
        installer_core.stage_content(assets, self.output)

        original_replace = installer_core.os.replace
        calls = 0

        def fail_content_stage(source, destination):
            nonlocal calls
            calls += 1
            if calls == len(installer_core.APP_ITEMS) + 3:
                raise OSError("injected content replace failure")
            return original_replace(source, destination)

        with mock.patch.object(installer_core.os, "replace", side_effect=fail_content_stage):
            with self.assertRaisesRegex(OSError, "injected content"):
                installer_core.commit(self.output)

        self.assertEqual(
            (self.output / "assets" / "sample.txt").read_text(encoding="utf-8"),
            "old-app",
        )
        self.assertEqual(
            (self.output / "presets" / "stale.milk").read_text(encoding="utf-8"),
            "old",
        )

    def test_manifest_records_component_details(self):
        installer_core.update_manifest_component(
            self.output,
            "python",
            "installed",
            {"version": "3.12.1", "requirements_sha256": "hash"},
        )
        manifest = json.loads((self.output / ".install-state.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["components"]["python"]["version"], "3.12.1")
        self.assertEqual(
            manifest["components"]["python"]["requirements_sha256"], "hash"
        )

    def test_projectm_component_stamp_checks_build_settings_and_artifact_hashes(self):
        artifact = self.root / "projectM.dll"
        artifact.write_bytes(b"projectm-binary")
        artifact_paths = {"projectM-4.dll": artifact}
        build_settings = {"cmake_flags": ["-DENABLE_GLES=OFF"], "arch": "x64"}

        installer_core.projectm_component(
            self.output,
            "stamp",
            "4.1.8",
            "core",
            "git",
            "master",
            "abc123",
            "Visual Studio 17 2022; CMake 3.31.8",
            build_settings,
            artifact_paths,
        )

        matching = installer_core.projectm_component(
            self.output,
            "check",
            "4.1.8",
            "core",
            "git",
            "master",
            "abc123",
            "Visual Studio 17 2022; CMake 3.31.8",
            build_settings,
            artifact_paths,
        )
        self.assertTrue(matching["matches"])
        artifact.write_bytes(b"changed-binary")
        changed = installer_core.projectm_component(
            self.output,
            "check",
            "4.1.8",
            "core",
            "git",
            "master",
            "abc123",
            "Visual Studio 17 2022; CMake 3.31.8",
            build_settings,
            artifact_paths,
        )
        self.assertFalse(changed["matches"])

    def test_projectm_component_requires_explicit_legacy_adoption(self):
        artifact = self.root / "projectM.dll"
        artifact.write_bytes(b"projectm-binary")
        installer_core.update_manifest_component(
            self.output,
            "projectm",
            "installed",
            {
                "version": "4.1.8",
                "renderer": "core",
                "ref": "master",
                "commit": "abc123",
                "built_with": "Visual Studio 17 2022",
                "cmake_flags": ["-DENABLE_GLES=OFF"],
                "artifacts_sha256": {
                    "projectM-4.dll": hashlib.sha256(artifact.read_bytes()).hexdigest()
                },
            },
        )
        arguments = (
            self.output,
            "check",
            "4.1.8",
            "core",
            "git",
            "master",
            "abc123",
            "Visual Studio 17 2022; CMake 3.31.8",
            {"cmake_flags": ["-DENABLE_GLES=OFF"]},
            {"projectM-4.dll": artifact},
        )
        self.assertFalse(installer_core.projectm_component(*arguments)["matches"])
        adopted = installer_core.projectm_component(
            *arguments, allow_legacy=True
        )
        self.assertTrue(adopted["matches"])
        self.assertTrue(adopted["legacy"])
        mismatched_flags = (
            *arguments[:-2],
            {"cmake_flags": ["-DENABLE_GLES=ON"]},
            arguments[-1],
        )
        rejected = installer_core.projectm_component(
            *mismatched_flags, allow_legacy=True
        )
        self.assertFalse(rejected["matches"])

    def test_projectm_legacy_stamp_without_artifact_hashes_cannot_be_adopted(self):
        artifact = self.root / "projectM.dll"
        artifact.write_bytes(b"projectm-binary")
        installer_core.update_manifest_component(
            self.output,
            "projectm",
            "installed",
            {
                "version": "4.1.8",
                "renderer": "core",
                "ref": "master",
                "commit": "abc123",
            },
        )
        result = installer_core.projectm_component(
            self.output,
            "check",
            "4.1.8",
            "core",
            "git",
            "master",
            "abc123",
            "toolchain",
            {},
            {"projectM-4.dll": artifact},
            allow_legacy=True,
        )
        self.assertFalse(result["matches"])

    def test_manifest_component_cli_decodes_base64_details(self):
        self.output.mkdir()
        details = {
            "built_with": "Visual Studio 17 2022",
            "cmake_flags": ["-DENABLE_GLES=OFF", "-DENABLE_PLAYLIST=ON"],
            "artifacts_sha256": {
                "projectM-4.dll": (
                    "4bbab69d363fc4c7d18b794d2ec73f6211d1fc84ac9dee158b29fcfdd8559566"
                )
            },
        }
        details_json = json.dumps(details, separators=(",", ":"))
        encoded_details = base64.b64encode(details_json.encode("utf-8")).decode("ascii")

        with mock.patch.object(
            sys,
            "argv",
            [
                "installer_core.py",
                "manifest-component",
                "--output",
                str(self.output),
                "--name",
                "projectm",
                "--status",
                "installed",
                "--details-base64",
                encoded_details,
            ],
        ):
            self.assertEqual(installer_core.main(), 0)

        manifest = json.loads((self.output / ".install-state.json").read_text(encoding="utf-8"))
        for key, value in details.items():
            self.assertEqual(manifest["components"]["projectm"][key], value)

    def test_manifest_operation_tracks_failure_without_success_timestamp(self):
        self.output.mkdir()
        (self.output / ".install-state.json").write_text(
            json.dumps(
                {
                    "last_mode": "update",
                    "last_profile": "optimized",
                    "options": {"autostart": True},
                    "projectm": {"version": "4.1.8"},
                }
            ),
            encoding="utf-8",
        )

        installer_core.manifest_operation(self.output, "begin")
        installer_core.update_manifest_component(
            self.output, "projectm", "in_progress"
        )
        installer_core.manifest_operation(self.output, "failed", "projectM build failed")

        manifest = json.loads((self.output / ".install-state.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "failed")
        self.assertEqual(manifest["attempt"]["status"], "failed")
        self.assertEqual(manifest["attempt"]["error"], "projectM build failed")
        self.assertEqual(manifest["components"]["projectm"]["status"], "failed")
        self.assertNotIn("version", manifest["components"]["projectm"])
        self.assertNotIn("installed_at", manifest)
        self.assertNotIn("updated_at", manifest)
        self.assertNotIn("options", manifest)
        self.assertNotIn("last_mode", manifest)
        self.assertNotIn("last_profile", manifest)

    def test_manifest_success_sets_first_install_and_update_timestamps(self):
        installer_core.manifest_operation(self.output, "begin")
        installer_core.update_manifest_component(
            self.output,
            "application",
            "installed",
            {"version": "1.2.3", "commit": "abc123"},
        )
        installer_core.manifest_operation(self.output, "succeeded")
        first = json.loads((self.output / ".install-state.json").read_text(encoding="utf-8"))
        installed_at = first["installed_at"]

        installer_core.manifest_operation(self.output, "begin")
        installer_core.update_manifest_component(
            self.output,
            "application",
            "installed",
            {"version": "1.2.4", "commit": "def456"},
        )
        installer_core.manifest_operation(self.output, "succeeded")
        updated = json.loads((self.output / ".install-state.json").read_text(encoding="utf-8"))

        self.assertEqual(updated["installed_at"], installed_at)
        self.assertGreaterEqual(updated["updated_at"], installed_at)
        self.assertEqual(updated["components"]["application"]["version"], "1.2.4")
        self.assertEqual(updated["status"], "succeeded")

    def test_manifest_migrates_legacy_fields_to_component_state(self):
        self.output.mkdir()
        legacy = {
            "app_version": "1.1.0",
            "installed_at": "legacy-timestamp",
            "source": {"ref": "v1.1.0", "commit": "abc"},
            "python": {
                "version": "3.12.1",
                "venv": "venv",
                "requirements_sha256": "hash",
            },
            "projectm": {"version": "4.1.8", "renderer": "core"},
            "content": {"visual_assets_commit": "assets-commit"},
            "options": {"autostart": True, "plugins": ["vlc"]},
            "last_mode": "update",
            "last_profile": "optimized",
        }
        (self.output / ".install-state.json").write_text(
            json.dumps(legacy), encoding="utf-8"
        )

        installer_core.manifest_operation(self.output, "begin")

        migrated = json.loads((self.output / ".install-state.json").read_text(encoding="utf-8"))
        self.assertEqual(migrated["components"]["application"]["version"], "1.1.0")
        self.assertEqual(migrated["components"]["application"]["commit"], "abc")
        self.assertEqual(migrated["components"]["python"]["requirements_sha256"], "hash")
        self.assertEqual(migrated["components"]["projectm"]["status"], "unverified")
        self.assertEqual(migrated["components"]["visual-assets"]["commit"], "assets-commit")
        self.assertEqual(migrated["components"]["autostart"]["state"], "installed")
        self.assertEqual(migrated["components"]["plugin-vlc"]["state"], "installed")
        self.assertNotIn("options", migrated)
        self.assertNotIn("last_mode", migrated)
        self.assertNotIn("last_profile", migrated)
        self.assertNotIn("installed_at", migrated)
        self.assertIn("legacy_state_migrated_at", migrated)

    def test_manifest_success_rejects_unfinished_components(self):
        installer_core.manifest_operation(self.output, "begin")
        installer_core.update_manifest_component(
            self.output, "application", "in_progress"
        )
        with self.assertRaisesRegex(RuntimeError, "still in progress"):
            installer_core.manifest_operation(self.output, "succeeded")

    def test_normal_uninstall_records_removed_app_and_preserves_retained_components(self):
        installer_core.manifest_operation(self.output, "begin")
        installer_core.update_manifest_component(
            self.output, "application", "installed", {"version": "1.2.3"}
        )
        installer_core.update_manifest_component(
            self.output, "autostart", "installed", {"state": "installed"}
        )
        installer_core.update_manifest_component(
            self.output, "projectm", "installed", {"version": "4.1.8"}
        )
        installer_core.manifest_operation(self.output, "succeeded")
        installed_at = json.loads(
            (self.output / ".install-state.json").read_text(encoding="utf-8")
        )["installed_at"]

        installer_core.manifest_operation(self.output, "begin")
        installer_core.update_manifest_component(
            self.output, "application", "in_progress"
        )
        installer_core.update_manifest_component(
            self.output, "autostart", "in_progress"
        )
        installer_core.update_manifest_component(self.output, "application", "removed")
        installer_core.update_manifest_component(self.output, "autostart", "removed")
        installer_core.manifest_operation(self.output, "succeeded")

        manifest = json.loads((self.output / ".install-state.json").read_text(encoding="utf-8"))
        application = manifest["components"]["application"]
        self.assertEqual(application["status"], "removed")
        self.assertNotIn("version", application)
        self.assertTrue(application["updated_at"])
        self.assertEqual(manifest["components"]["autostart"]["status"], "removed")
        self.assertEqual(manifest["components"]["projectm"]["status"], "installed")
        self.assertEqual(manifest["components"]["projectm"]["version"], "4.1.8")
        self.assertEqual(manifest["status"], "succeeded")
        self.assertEqual(manifest["installed_at"], installed_at)

    def test_installer_api_guard_rejects_newer_source(self):
        source_version = self.root / "VERSION"
        source_version.write_text("INSTALLER_API=2\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "requires installer API 2"):
            installer_core.verify_installer_api(source_version, supported_api=1)

    def test_latest_release_strips_git_suffix_from_github_url(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        with mock.patch.object(installer_core.urllib.request, "urlopen", return_value=response) as urlopen:
            response.read.return_value = b'{"tag_name":"v1.2.3"}'
            with mock.patch.object(installer_core.json, "load", return_value={"tag_name": "v1.2.3"}):
                tag = installer_core.resolve_latest_release("https://github.com/owner/project.git")

        self.assertEqual(tag, "v1.2.3")
        self.assertEqual(
            urlopen.call_args.args[0].full_url,
            "https://api.github.com/repos/owner/project/releases/latest",
        )

    def test_default_checkout_resolves_release_but_explicit_ref_is_preserved(self):
        config = (Path(__file__).parents[1] / "bin" / "installer.env").read_text(
            encoding="utf-8"
        )
        values = dict(line.split("=", 1) for line in config.splitlines() if line and not line.startswith("#"))
        cache = self.root / "cache"
        (cache / ".git").mkdir(parents=True)
        repository = "https://github.com/owner/project.git"
        with (
            mock.patch.object(installer_core, "resolve_latest_release", return_value="v1.2.3") as latest,
            mock.patch.object(installer_core, "run_git", return_value="commit") as git,
            mock.patch.object(installer_core.subprocess, "run") as describe,
        ):
            describe.return_value.returncode = 1
            installer_core.checkout(repository, values["APP_DEFAULT_REF"], cache)
            latest.assert_called_once_with(repository)
            git.assert_any_call(["fetch", "--force", "--prune", "origin", "v1.2.3"], cwd=cache)

            latest.reset_mock()
            git.reset_mock()
            installer_core.checkout(repository, "main", cache)
            latest.assert_not_called()
            git.assert_any_call(["fetch", "--force", "--prune", "origin", "main"], cwd=cache)


if __name__ == "__main__":
    unittest.main()
