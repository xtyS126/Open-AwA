import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from plugins.cli.plugin_cli import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestCmdInit:
    def test_creates_expected_files(self, runner: CliRunner, tmp_path: Path) -> None:
        target = tmp_path / "my-plugin"
        result = runner.invoke(
            cli,
            ["init", str(target), "--name", "@scope/my-plugin", "--version", "1.2.3"],
        )
        assert result.exit_code == 0, result.output
        assert (target / "manifest.json").exists()
        assert (target / "src" / "index.py").exists()
        assert (target / "README.md").exists()
        assert (target / "LICENSE").exists()

    def test_manifest_content_is_valid(self, runner: CliRunner, tmp_path: Path) -> None:
        target = tmp_path / "valid-plugin"
        runner.invoke(
            cli,
            [
                "init",
                str(target),
                "--name",
                "@org/valid",
                "--version",
                "0.1.0",
                "--author",
                "tester",
                "--description",
                "desc",
            ],
        )
        manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["name"] == "@org/valid"
        assert manifest["version"] == "0.1.0"
        assert manifest["author"] == "tester"
        assert manifest["pluginApiVersion"] == "1.0.0"
        assert len(manifest["extensions"]) == 1
        assert manifest["extensions"][0]["point"] == "tool"

    def test_fails_if_dir_exists(self, runner: CliRunner, tmp_path: Path) -> None:
        existing = tmp_path / "exists"
        existing.mkdir()
        result = runner.invoke(cli, ["init", str(existing), "--name", "@s/p"])
        assert result.exit_code != 0


class TestCmdBuild:
    def _make_plugin_dir(self, base: Path, name: str = "@scope/plug", version: str = "1.0.0") -> Path:
        d = base / "plugin"
        d.mkdir()
        manifest = {
            "name": name,
            "version": version,
            "pluginApiVersion": "1.0.0",
            "description": "test",
            "author": "tester",
            "permissions": [],
            "extensions": [{"point": "tool", "name": "plug", "version": version}],
        }
        (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (d / "README.md").write_text("readme", encoding="utf-8")
        (d / "LICENSE").write_text("MIT", encoding="utf-8")
        return d

    def test_creates_zip_with_correct_name(self, runner: CliRunner, tmp_path: Path) -> None:
        plugin_dir = self._make_plugin_dir(tmp_path, "@scope/plug", "2.0.0")
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        result = runner.invoke(cli, ["build", str(plugin_dir), "-o", str(out_dir)])
        assert result.exit_code == 0, result.output
        zip_file = out_dir / "scope-plug@2.0.0.zip"
        assert zip_file.exists()

    def test_zip_contains_required_entries(self, runner: CliRunner, tmp_path: Path) -> None:
        plugin_dir = self._make_plugin_dir(tmp_path)
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        runner.invoke(cli, ["build", str(plugin_dir), "-o", str(out_dir)])
        zips = list(out_dir.glob("*.zip"))
        assert len(zips) == 1
        with zipfile.ZipFile(zips[0]) as zf:
            names = zf.namelist()
        assert "manifest.json" in names
        assert "README.md" in names
        assert "LICENSE" in names
        assert any(n.startswith("dist/") for n in names)

    def test_fails_without_manifest(self, runner: CliRunner, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        result = runner.invoke(cli, ["build", str(empty)])
        assert result.exit_code != 0

    def test_includes_dist_files_when_present(self, runner: CliRunner, tmp_path: Path) -> None:
        plugin_dir = self._make_plugin_dir(tmp_path)
        dist = plugin_dir / "dist"
        dist.mkdir()
        (dist / "index.js").write_text("export {}", encoding="utf-8")
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        runner.invoke(cli, ["build", str(plugin_dir), "-o", str(out_dir)])
        zips = list(out_dir.glob("*.zip"))
        with zipfile.ZipFile(zips[0]) as zf:
            names = zf.namelist()
        assert "dist/index.js" in names


class TestCmdValidate:
    def _make_valid_zip(self, tmp_path: Path, name: str = "test-plugin@1.0.0.zip") -> Path:
        manifest = {
            "name": "@test/plugin",
            "version": "1.0.0",
            "pluginApiVersion": "1.0.0",
            "description": "d",
            "author": "a",
            "permissions": [],
            "extensions": [{"point": "tool", "name": "p", "version": "1.0.0"}],
        }
        zip_path = tmp_path / name
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("manifest.json", json.dumps(manifest))
            zf.writestr("README.md", "readme")
            zf.writestr("LICENSE", "MIT")
            zf.writestr("dist/.gitkeep", "")
        return zip_path

    def test_valid_zip_passes(self, runner: CliRunner, tmp_path: Path) -> None:
        zip_path = self._make_valid_zip(tmp_path)
        result = runner.invoke(cli, ["validate", str(zip_path)])
        assert result.exit_code == 0
        assert "验证通过" in result.output

    def test_missing_manifest_fails(self, runner: CliRunner, tmp_path: Path) -> None:
        zip_path = tmp_path / "no-manifest.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("README.md", "readme")
        result = runner.invoke(cli, ["validate", str(zip_path)])
        assert result.exit_code != 0

    def test_invalid_manifest_schema_fails(self, runner: CliRunner, tmp_path: Path) -> None:
        zip_path = tmp_path / "bad-manifest.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("manifest.json", json.dumps({"name": "only-name"}))
            zf.writestr("README.md", "r")
            zf.writestr("LICENSE", "l")
            zf.writestr("dist/.gitkeep", "")
        result = runner.invoke(cli, ["validate", str(zip_path)])
        assert result.exit_code != 0

    def test_nonexistent_file_fails(self, runner: CliRunner, tmp_path: Path) -> None:
        result = runner.invoke(cli, ["validate", str(tmp_path / "ghost.zip")])
        assert result.exit_code != 0


class TestCmdSign:
    def _make_zip(self, tmp_path: Path) -> Path:
        zip_path = tmp_path / "plugin@1.0.0.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("manifest.json", "{\"hello\": \"world\"}")
        return zip_path

    def test_creates_signature_json(self, runner: CliRunner, tmp_path: Path) -> None:
        zip_path = self._make_zip(tmp_path)
        result = runner.invoke(cli, ["sign", str(zip_path)])
        assert result.exit_code == 0, result.output
        sig_path = tmp_path / "signature.json"
        assert sig_path.exists()

    def test_signature_sha256_is_correct(self, runner: CliRunner, tmp_path: Path) -> None:
        zip_path = self._make_zip(tmp_path)
        expected = hashlib.sha256(zip_path.read_bytes()).hexdigest()
        runner.invoke(cli, ["sign", str(zip_path)])
        sig = json.loads((tmp_path / "signature.json").read_text(encoding="utf-8"))
        assert sig["sha256"] == expected
        assert sig["algorithm"] == "sha256"
        assert sig["file"] == zip_path.name

    def test_custom_output_path(self, runner: CliRunner, tmp_path: Path) -> None:
        zip_path = self._make_zip(tmp_path)
        out = tmp_path / "custom_sig.json"
        result = runner.invoke(cli, ["sign", str(zip_path), "-o", str(out)])
        assert result.exit_code == 0
        assert out.exists()

    def test_nonexistent_zip_fails(self, runner: CliRunner, tmp_path: Path) -> None:
        result = runner.invoke(cli, ["sign", str(tmp_path / "ghost.zip")])
        assert result.exit_code != 0
