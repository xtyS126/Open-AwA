import hashlib
import json
import zipfile
from pathlib import Path

import click

from plugins.schema_validator import ManifestExtensionSchemaValidator


@click.group()
def cli():
    pass


@cli.command("init")
@click.argument("plugin_dir")
@click.option("--name", required=True, help="插件名称，如 @scope/my-plugin")
@click.option("--version", default="1.0.0", show_default=True, help="插件版本")
@click.option("--author", default="", help="作者")
@click.option("--description", default="A new plugin", help="插件描述")
def cmd_init(plugin_dir: str, name: str, version: str, author: str, description: str) -> None:
    target = Path(plugin_dir)
    if target.exists():
        raise click.ClickException(f"目录已存在：{plugin_dir}")

    target.mkdir(parents=True)
    (target / "src").mkdir()

    extension_name = name.lstrip("@").replace("/", "-")
    manifest: dict = {
        "name": name,
        "version": version,
        "pluginApiVersion": "1.0.0",
        "description": description,
        "author": author,
        "permissions": [],
        "extensions": [
            {
                "point": "tool",
                "name": extension_name,
                "version": version,
            }
        ],
    }
    (target / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (target / "src" / "index.py").write_text(
        "def run(**kwargs):\n    pass\n", encoding="utf-8"
    )
    (target / "README.md").write_text(f"# {name}\n\n{description}\n", encoding="utf-8")
    (target / "LICENSE").write_text("MIT License\n", encoding="utf-8")

    click.echo(f"插件模板已生成：{plugin_dir}")


@cli.command("build")
@click.argument("plugin_dir")
@click.option("--output", "-o", default=".", show_default=True, help="输出目录")
def cmd_build(plugin_dir: str, output: str) -> None:
    src = Path(plugin_dir)
    manifest_path = src / "manifest.json"
    if not manifest_path.exists():
        raise click.ClickException("manifest.json 不存在")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"manifest.json 解析失败：{exc}") from exc

    name: str = manifest.get("name", "plugin")
    version: str = manifest.get("version", "0.0.0")
    safe_name = name.lstrip("@").replace("/", "-")
    zip_name = f"{safe_name}@{version}.zip"
    zip_path = Path(output) / zip_name

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(manifest_path, "manifest.json")

        for extra in ("README.md", "LICENSE"):
            p = src / extra
            if p.exists():
                zf.write(p, extra)

        dist_dir = src / "dist"
        if dist_dir.exists() and dist_dir.is_dir():
            for file in dist_dir.rglob("*"):
                if file.is_file():
                    zf.write(file, str(file.relative_to(src)).replace("\\", "/"))
        else:
            zf.writestr("dist/.gitkeep", "")

    click.echo(f"已打包：{zip_path}")


@cli.command("validate")
@click.argument("zip_path")
def cmd_validate(zip_path: str) -> None:
    path = Path(zip_path)
    if not path.exists():
        raise click.ClickException(f"文件不存在：{zip_path}")

    try:
        zf_handle = zipfile.ZipFile(path, "r")
    except zipfile.BadZipFile as exc:
        raise click.ClickException(f"不是有效的 zip 文件：{zip_path}") from exc

    errors: list = []
    with zf_handle as zf:
        names = zf.namelist()

        if "manifest.json" not in names:
            raise click.ClickException("zip 中缺少 manifest.json")

        for required in ("README.md", "LICENSE"):
            if required not in names:
                errors.append(f"缺少文件：{required}")

        has_dist = any(n.startswith("dist/") for n in names)
        if not has_dist:
            errors.append("缺少 dist/ 目录")

        try:
            manifest_data = json.loads(zf.read("manifest.json").decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise click.ClickException(f"manifest.json 解析失败：{exc}") from exc

    validator = ManifestExtensionSchemaValidator()
    result = validator.validate_manifest(manifest_data)
    if not result.valid:
        for err in result.errors:
            errors.append(f"manifest 校验失败：{err}")

    if errors:
        for err in errors:
            click.echo(f"错误：{err}", err=True)
        raise SystemExit(1)

    click.echo("验证通过")


@cli.command("sign")
@click.argument("zip_path")
@click.option(
    "--output", "-o", default=None, help="signature.json 输出路径，默认与 zip 同目录"
)
def cmd_sign(zip_path: str, output: str | None) -> None:
    path = Path(zip_path)
    if not path.exists():
        raise click.ClickException(f"文件不存在：{zip_path}")

    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    signature = {
        "file": path.name,
        "algorithm": "sha256",
        "sha256": sha256,
    }

    if output is None:
        sig_path = path.parent / "signature.json"
    else:
        sig_path = Path(output)

    sig_path.write_text(json.dumps(signature, indent=2, ensure_ascii=False), encoding="utf-8")
    click.echo(f"签名已生成：{sig_path}")
