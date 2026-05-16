#!/usr/bin/env python3
"""
file_searcher.py — 本地文件搜索工具

功能：
  1. 按文件名模式搜索（glob 语法，如 *.txt、*.py）
  2. 按文本内容搜索（UTF-8 编码）
  3. 命令行参数控制搜索方式与目标路径
  4. 输出匹配文件列表及总数统计
  5. 优雅处理权限不足、二进制文件、编码错误等异常

用法：
  python file_searcher.py --name "*.py" /some/path
  python file_searcher.py --content "TODO" /some/path
  python file_searcher.py --name "*.md"           # 默认搜索当前目录
"""

import os
import sys
import argparse
import fnmatch
import time


def search_by_name(root_dir: str, pattern: str) -> list[str]:
    """
    递归遍历 root_dir，返回所有与 pattern（glob 风格）匹配的文件路径列表。
    """
    matched: list[str] = []
    # 将用户输入的 pattern 统一为小写以支持大小写不敏感匹配
    # （Windows 文件系统大小写不敏感，这里保持原样即可）
    for dirpath, dirnames, filenames in os.walk(root_dir):
        for filename in filenames:
            if fnmatch.fnmatch(filename, pattern):
                full_path = os.path.join(dirpath, filename)
                matched.append(full_path)
    return matched


def is_text_file(file_path: str, sample_size: int = 8192) -> bool:
    """
    简单判断文件是否为文本文件：读取前 sample_size 字节，
    如果包含空字节则判定为二进制文件。
    """
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(sample_size)
        return b"\0" not in chunk
    except OSError:
        return False


def search_by_content(root_dir: str, keyword: str) -> list[str]:
    """
    递归遍历 root_dir，搜索包含 keyword 的文本文件（UTF-8 编码）。
    返回匹配的文件路径列表。
    """
    matched: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root_dir):
        for filename in filenames:
            full_path = os.path.join(dirpath, filename)

            # 1) 权限检查：尝试以只读方式打开
            if not os.access(full_path, os.R_OK):
                # 权限不足，跳过并提示
                print(f"[警告] 权限不足，跳过: {full_path}", file=sys.stderr)
                continue

            # 2) 文本/二进制判断
            if not is_text_file(full_path):
                continue

            # 3) 尝试按 UTF-8 读取并搜索关键词
            try:
                with open(full_path, "r", encoding="utf-8", errors="strict") as f:
                    # 逐行读取以节省内存
                    found = False
                    for line in f:
                        if keyword in line:
                            found = True
                            break
                    if found:
                        matched.append(full_path)
            except UnicodeDecodeError:
                # UTF-8 解码失败，尝试常见中文编码（GBK）作为后备
                try:
                    with open(full_path, "r", encoding="gbk", errors="strict") as f:
                        found = False
                        for line in f:
                            if keyword in line:
                                found = True
                                break
                        if found:
                            matched.append(full_path)
                except (UnicodeDecodeError, LookupError):
                    # 编码不确定，跳过
                    print(f"[警告] 无法识别编码，跳过: {full_path}", file=sys.stderr)
                    continue
            except OSError as e:
                print(f"[警告] 读取文件失败 ({e})，跳过: {full_path}", file=sys.stderr)
                continue

    return matched


def resolve_path(path_arg: str | None) -> str:
    """解析路径参数，如果为 None 则返回当前目录。"""
    if path_arg is None:
        return os.getcwd()
    # 展开用户主目录 ~ 并转为绝对路径
    expanded = os.path.expanduser(path_arg)
    return os.path.abspath(expanded)


def setup_argparse() -> argparse.ArgumentParser:
    """配置命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        description="file_searcher.py — 本地文件搜索工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  %(prog)s --name \"*.py\" /some/path\n"
            "  %(prog)s --content \"TODO\" /some/path\n"
            "  %(prog)s --name \"*.md\"              # 默认搜索当前目录\n"
        ),
    )

    # 搜索模式互斥组：--name 和 --content 二选一（也可以都不选，给提示）
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--name", "-n",
        type=str,
        metavar="PATTERN",
        help="按文件名模式搜索（支持 glob 语法，例如 *.txt、*.py）",
    )
    mode_group.add_argument(
        "--content", "-c",
        type=str,
        metavar="KEYWORD",
        help="按文件内容搜索关键词（UTF-8 编码）",
    )

    parser.add_argument(
        "path",
        type=str,
        nargs="?",
        default=None,
        help="要搜索的目录路径（默认当前目录）",
    )

    return parser


def main() -> None:
    """主函数：解析参数、执行搜索、输出结果。"""
    parser = setup_argparse()
    args = parser.parse_args()

    # 检查是否至少指定了一种搜索模式
    if not args.name and not args.content:
        parser.print_help()
        print("\n[错误] 请指定搜索模式：--name 或 --content", file=sys.stderr)
        sys.exit(1)

    # 解析并校验目标路径
    target_dir = resolve_path(args.path)
    if not os.path.isdir(target_dir):
        print(f"[错误] 路径不存在或不是目录: {target_dir}", file=sys.stderr)
        sys.exit(1)

    # 执行搜索
    start_time = time.time()

    if args.name:
        print(f"🔍 按文件名模式搜索: \"{args.name}\"")
        print(f"   目标目录: {target_dir}")
        print("-" * 60)
        results = search_by_name(target_dir, args.name)
    else:
        print(f"🔍 按文件内容搜索关键词: \"{args.content}\"")
        print(f"   目标目录: {target_dir}")
        print("-" * 60)
        results = search_by_content(target_dir, args.content)

    elapsed = time.time() - start_time

    # 输出结果
    if not results:
        print("未找到匹配的文件。")
    else:
        print(f"\n匹配结果（共 {len(results)} 个文件）:\n")
        for i, file_path in enumerate(results, start=1):
            print(f"  {i:>4}. {file_path}")

    print(f"\n✅ 搜索完成，耗时 {elapsed:.3f} 秒")


if __name__ == "__main__":
    main()
