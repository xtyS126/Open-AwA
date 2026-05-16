#!/usr/bin/env python3
"""
batch_renamer.py — 命令行批量文件重命名工具

功能：
  1. 替换模式：将文件名中的指定字符串替换为另一个字符串
  2. 添加前缀/后缀：为所有文件统一添加前缀或后缀
  3. 序号重命名：按序号格式重命名文件
  4. 扩展名修改：批量修改文件扩展名
  5. 正则替换：支持正则表达式匹配替换

用法示例：
  python batch_renamer.py <目录> --replace "旧文本" "新文本" [-r] [--dry-run]
  python batch_renamer.py <目录> --prefix "前缀_" [-r] [--dry-run]
  python batch_renamer.py <目录> --suffix "_后缀" [-r] [--dry-run]
  python batch_renamer.py <目录> --number --format "文件_{:03d}" --start 1 [-r] [--dry-run]
  python batch_renamer.py <目录> --ext txt md [-r] [--dry-run]
  python batch_renamer.py <目录> --regex "模式" "替换为" [-r] [--dry-run]
"""

import os
import re
import sys
import argparse
from pathlib import Path
from collections import namedtuple

# 表示一个重命名操作
RenameOp = namedtuple("RenameOp", ["src", "dst"])


def collect_files(directory: Path, recursive: bool) -> list[Path]:
    """收集目录下所有文件（不包含目录本身）。"""
    if recursive:
        files = [p for p in directory.rglob("*") if p.is_file()]
    else:
        files = [p for p in directory.glob("*") if p.is_file()]
    # 按路径排序使结果稳定可复现
    files.sort()
    return files


def safe_rename(src: Path, dst: Path, dry_run: bool) -> tuple[bool, str]:
    """
    安全地重命名文件，返回 (成功?, 消息)。
    不实际执行时只做校验，不修改文件系统。
    """
    # 检查源文件是否存在（以防在收集后被人为删除）
    if not src.exists():
        return False, f"源文件不存在: {src}"

    # 如果源和目标相同，跳过
    if src == dst:
        return False, f"源和目标相同，跳过: {src.name}"

    # 检查目标文件是否已存在（且不是源自身）
    if dst.exists():
        return False, f"目标文件已存在，跳过: {dst.name}"

    # 检查权限（父目录是否可写）
    if not os.access(src.parent, os.W_OK):
        return False, f"目录不可写: {src.parent}"

    if dry_run:
        return True, f"[模拟] {src.name} -> {dst.name}"
    else:
        try:
            src.rename(dst)
            return True, f"{src.name} -> {dst.name}"
        except PermissionError:
            return False, f"权限错误: 无法重命名 {src.name}"
        except OSError as e:
            return False, f"重命名失败 {src.name}: {e}"


def mode_replace(files: list[Path], old: str, new: str) -> list[RenameOp]:
    """替换模式：将文件名中的 old 替换为 new。"""
    ops = []
    for f in files:
        new_name = f.name.replace(old, new)
        if new_name != f.name:
            ops.append(RenameOp(src=f, dst=f.with_name(new_name)))
    return ops


def mode_prefix(files: list[Path], prefix: str) -> list[RenameOp]:
    """添加前缀。"""
    ops = []
    for f in files:
        new_name = prefix + f.name
        # 如果加前缀后名字没变（前缀为空），跳过
        if new_name != f.name:
            ops.append(RenameOp(src=f, dst=f.with_name(new_name)))
    return ops


def mode_suffix(files: list[Path], suffix: str) -> list[RenameOp]:
    """添加后缀（在扩展名之前）。"""
    ops = []
    for f in files:
        stem = f.stem
        ext = f.suffix
        new_name = stem + suffix + ext
        if new_name != f.name:
            ops.append(RenameOp(src=f, dst=f.with_name(new_name)))
    return ops


def mode_number(
    files: list[Path],
    fmt: str,
    start: int,
    sort_key: str,
) -> list[RenameOp]:
    """序号重命名。
    fmt: 格式化字符串，如 "文件_{:03d}"
    start: 起始序号
    sort_key: 排序方式，name / mtime / ctime
    """
    if sort_key == "name":
        sorted_files = sorted(files, key=lambda p: p.name)
    elif sort_key == "mtime":
        sorted_files = sorted(files, key=lambda p: p.stat().st_mtime)
    elif sort_key == "ctime":
        sorted_files = sorted(files, key=lambda p: p.stat().st_ctime)
    else:
        sorted_files = files

    ops = []
    for i, f in enumerate(sorted_files):
        ext = f.suffix
        base = fmt.format(start + i)
        new_name = base + ext
        ops.append(RenameOp(src=f, dst=f.with_name(new_name)))
    return ops


def mode_ext(files: list[Path], old_ext: str, new_ext: str) -> list[RenameOp]:
    """修改扩展名。只处理扩展名为 old_ext 的文件。"""
    # 规范化扩展名，确保带点
    old_ext = f".{old_ext.lstrip('.')}"
    new_ext = f".{new_ext.lstrip('.')}"

    ops = []
    for f in files:
        if f.suffix.lower() == old_ext.lower():
            new_name = f.stem + new_ext
            ops.append(RenameOp(src=f, dst=f.with_name(new_name)))
    return ops


def mode_regex(files: list[Path], pattern: str, repl: str) -> list[RenameOp]:
    """正则替换模式。"""
    try:
        compiled = re.compile(pattern)
    except re.error as e:
        print(f"错误: 正则表达式无效 — {e}", file=sys.stderr)
        sys.exit(1)

    ops = []
    for f in files:
        new_name = compiled.sub(repl, f.name)
        if new_name != f.name:
            ops.append(RenameOp(src=f, dst=f.with_name(new_name)))
    return ops


def resolve_conflicts(ops: list[RenameOp]) -> list[RenameOp]:
    """
    检测并解决目标文件名冲突。
    如果有多个文件要重命名为同一个目标，只保留第一个，其余标记跳过。
    返回过滤后的操作列表。
    """
    seen: set[Path] = set()
    resolved = []
    for op in ops:
        if op.dst in seen:
            print(f"  警告: 目标文件重复，跳过: {op.src.name} -> {op.dst.name}")
            continue
        seen.add(op.dst)
        resolved.append(op)
    return resolved


def execute_ops(ops: list[RenameOp], dry_run: bool) -> dict:
    """执行重命名操作列表，返回统计信息。"""
    stats = {"success": 0, "skipped": 0, "error": 0}

    # 先检测冲突
    ops = resolve_conflicts(ops)

    for op in ops:
        success, msg = safe_rename(op.src, op.dst, dry_run)
        if success:
            stats["success"] += 1
        else:
            # 区分跳过和错误
            if "跳过" in msg or "相同" in msg or "已存在" in msg:
                stats["skipped"] += 1
            else:
                stats["error"] += 1
        print(f"  {msg}")

    return stats


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="batch_renamer.py",
        description="命令行批量文件重命名工具 — 支持替换、前缀/后缀、序号、扩展名修改、正则替换",
        epilog=(
            "示例:\n"
            "  %(prog)s ./photos --replace \"IMG_\" \"Photo_\" -r --dry-run\n"
            "  %(prog)s ./docs --prefix \"draft_\"\n"
            "  %(prog)s ./files --suffix \"_final\" -r\n"
            "  %(prog)s ./images --number --format \"img_{:03d}\" --start 100\n"
            "  %(prog)s ./data --ext txt md -r\n"
            "  %(prog)s ./logs --regex \"\\d{4}-\\d{2}-\\d{2}\" \"DATE\" --dry-run"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "directory",
        type=str,
        help="要处理的目录路径",
    )

    # 互斥操作组 —— 一次只能选一种模式
    mode_group = parser.add_argument_group("操作模式（必须指定其中一种）")

    mode_group.add_argument(
        "--replace",
        nargs=2,
        metavar=("旧文本", "新文本"),
        help="替换模式：将文件名中的 <旧文本> 替换为 <新文本>",
    )

    mode_group.add_argument(
        "--prefix",
        type=str,
        metavar="前缀",
        help="添加前缀模式：为所有文件名添加指定前缀",
    )

    mode_group.add_argument(
        "--suffix",
        type=str,
        metavar="后缀",
        help="添加后缀模式：为所有文件名添加指定后缀（在扩展名之前）",
    )

    mode_group.add_argument(
        "--number",
        action="store_true",
        help="序号重命名模式：按序号格式重命名文件（需配合 --format 使用）",
    )

    mode_group.add_argument(
        "--ext",
        nargs=2,
        metavar=("旧扩展名", "新扩展名"),
        help="修改扩展名模式：将文件的 <旧扩展名> 改为 <新扩展名>",
    )

    mode_group.add_argument(
        "--regex",
        nargs=2,
        metavar=("正则模式", "替换为"),
        help="正则替换模式：使用正则表达式匹配并替换文件名",
    )

    # 序号模式的额外选项
    number_group = parser.add_argument_group("序号模式选项")
    number_group.add_argument(
        "--format",
        type=str,
        default="文件_{:03d}",
        metavar="格式字符串",
        help='序号重命名的格式字符串，如 "文件_{:03d}"（默认: "文件_{:03d}"）',
    )
    number_group.add_argument(
        "--start",
        type=int,
        default=1,
        metavar="起始序号",
        help="序号起始值（默认: 1）",
    )
    number_group.add_argument(
        "--sort",
        type=str,
        choices=["name", "mtime", "ctime"],
        default="name",
        metavar="排序方式",
        help="序号排序方式: name(按名称) / mtime(按修改时间) / ctime(按创建时间)（默认: name）",
    )

    # 通用选项
    general_group = parser.add_argument_group("通用选项")
    general_group.add_argument(
        "-r", "--recursive",
        action="store_true",
        help="递归处理子目录",
    )
    general_group.add_argument(
        "--dry-run",
        action="store_true",
        help="预览模式/模拟运行：只显示将要执行的操作，不实际改名",
    )

    return parser


def validate_args(args: argparse.Namespace) -> None:
    """校验参数合法性。"""
    # 确保至少指定了一种操作模式
    modes = [args.replace, args.prefix, args.suffix, args.number, args.ext, args.regex]
    active_count = sum(1 for m in modes if m is not None and m is not False)
    if active_count == 0:
        print("错误: 必须指定一种操作模式（--replace / --prefix / --suffix / --number / --ext / --regex）",
              file=sys.stderr)
        sys.exit(1)
    if active_count > 1:
        print("错误: 一次只能使用一种操作模式", file=sys.stderr)
        sys.exit(1)

    # 如果指定了 --number，检查是否有文件匹配
    # （在文件收集后再判断即可）

    # 如果指定了 --regex，测试正则是否有效
    if args.regex:
        try:
            re.compile(args.regex[0])
        except re.error as e:
            print(f"错误: 正则表达式无效 — {e}", file=sys.stderr)
            sys.exit(1)


def main():
    parser = build_parser()
    args = parser.parse_args()

    # 参数校验
    validate_args(args)

    # 解析目录
    directory = Path(args.directory).resolve()
    if not directory.exists():
        print(f"错误: 目录不存在: {directory}", file=sys.stderr)
        sys.exit(1)
    if not directory.is_dir():
        print(f"错误: 路径不是一个目录: {directory}", file=sys.stderr)
        sys.exit(1)

    # 收集文件
    files = collect_files(directory, args.recursive)
    if not files:
        print("没有找到任何文件。")
        sys.exit(0)

    print(f"找到 {len(files)} 个文件")
    if args.recursive:
        print("（已启用递归子目录）")
    print()

    # 根据模式生成操作列表
    ops: list[RenameOp] = []

    if args.replace:
        old_text, new_text = args.replace
        ops = mode_replace(files, old_text, new_text)
        print(f"模式: 替换  \"{old_text}\" -> \"{new_text}\"")
    elif args.prefix:
        ops = mode_prefix(files, args.prefix)
        print(f"模式: 添加前缀 \"{args.prefix}\"")
    elif args.suffix:
        ops = mode_suffix(files, args.suffix)
        print(f"模式: 添加后缀 \"{args.suffix}\"")
    elif args.number:
        ops = mode_number(files, args.format, args.start, args.sort)
        print(f"模式: 序号重命名 格式=\"{args.format}\" 起始={args.start} 排序={args.sort}")
    elif args.ext:
        old_ext, new_ext = args.ext
        ops = mode_ext(files, old_ext, new_ext)
        print(f"模式: 修改扩展名 .{old_ext.lstrip('.')} -> .{new_ext.lstrip('.')}")
    elif args.regex:
        pattern, repl = args.regex
        ops = mode_regex(files, pattern, repl)
        print(f"模式: 正则替换  \"{pattern}\" -> \"{repl}\"")

    # 过滤掉空操作
    ops = [op for op in ops if op.src != op.dst]

    if not ops:
        print("\n没有需要重命名的文件。")
        sys.exit(0)

    print(f"将要执行 {len(ops)} 个重命名操作")
    if args.dry_run:
        print("（预览模式，不会实际修改文件）")
    print()

    # 执行
    stats = execute_ops(ops, dry_run=args.dry_run)

    # 统计信息
    print(f"\n{'='*40}")
    print("执行统计:")
    print(f"  成功: {stats['success']}")
    print(f"  跳过: {stats['skipped']}")
    print(f"  错误: {stats['error']}")
    print(f"{'='*40}")

    if args.dry_run:
        print("（预览模式，未实际修改任何文件）")


if __name__ == "__main__":
    main()
