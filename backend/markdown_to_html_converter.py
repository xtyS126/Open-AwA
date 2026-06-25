#!/usr/bin/env python3
"""
Markdown to HTML Converter

一个实用的 Markdown 转 HTML 工具，支持基本的 Markdown 语法，
包括标题、粗体、斜体、列表、代码块、链接和图片。

用法:
    python markdown_to_html_converter.py input.md [-o output.html]
    python markdown_to_html_converter.py input.md --output output.html

如果未指定输出路径，默认输出到输入文件同目录下的 output.html。

支持的 Markdown 语法:
    - 标题 (h1-h6): # ~ ######
    - 粗体: **text** 或 __text__
    - 斜体: *text* 或 _text_
    - 无序列表: - / * / +
    - 有序列表: 1. 2. 3. ...
    - 行内代码: `code`
    - 围栏代码块: ``` ... ```
    - 链接: [text](url)
    - 图片: ![alt](url)
    - 水平线: --- / *** / ___
    - 引用: > text
"""

import argparse
import os
import re
import sys
from typing import List, Tuple

from loguru import logger


def escape_html(text: str) -> str:
    """
    转义 HTML 特殊字符。

    在 Markdown 正文中，&、<、> 需要被转义为 HTML 实体，
    以防止 XSS 攻击并确保内容正确显示。

    Args:
        text: 原始文本

    Returns:
        转义后的文本
    """
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


def unescape_html(text: str) -> str:
    """将 HTML 实体还原（用于代码块内部，保持原始内容）。"""
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    return text


def convert_inline_formatting(text: str) -> str:
    """
    转换行内格式：粗体、斜体、行内代码、链接、图片。

    处理顺序很重要：
    1. 行内代码（最高优先级，内部不再解析）
    2. 图片 ![...](...)
    3. 链接 [...](...)
    4. 粗体 **...** 和 __...__
    5. 斜体 *...* 和 _..._

    Args:
        text: 单行文本（已转义 HTML 实体）

    Returns:
        HTML 格式的文本
    """
    # 1) 行内代码：`...` → <code>...</code>
    #    使用占位符保护，防止内部内容被后续正则误处理
    inline_code_pattern = re.compile(r'`([^`]+)`')
    text = inline_code_pattern.sub(r'<code>\1</code>', text)

    # 2) 图片：![alt](url) → <img src="url" alt="alt">
    text = re.sub(
        r'!\[([^\]]*)\]\(([^)\s]+(?:\s+"[^"]*")?)\)',
        r'<img src="\2" alt="\1">',
        text
    )

    # 3) 链接：[text](url) → <a href="url">text</a>
    text = re.sub(
        r'(?<!!)\[([^\]]*)\]\(([^)\s]+)\)',
        r'<a href="\2">\1</a>',
        text
    )

    # 4) 粗体：**text** 或 __text__ → <strong>text</strong>
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'__(.+?)__', r'<strong>\1</strong>', text)

    # 5) 斜体：*text* 或 _text_ → <em>text</em>
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    text = re.sub(r'_(.+?)_', r'<em>\1</em>', text)

    return text


def convert_markdown_to_html(markdown_text: str) -> str:
    """
    将 Markdown 格式文本转换为完整的 HTML 文档。

    转换流程：
    1. 移除行尾空白
    2. 提取并保护围栏代码块（用占位符替换）
    3. 按空行分割为段落块
    4. 对每个段落块判断类型并转换
    5. 对普通段落应用行内格式转换
    6. 还原围栏代码块
    7. 包裹为完整 HTML 文档

    Args:
        markdown_text: Markdown 格式的原始文本

    Returns:
        完整的 HTML 文档字符串
    """
    lines = markdown_text.split('\n')

    # ---------- 第1步：移除行尾空白 ----------
    lines = [line.rstrip() for line in lines]

    # ---------- 第2步：提取围栏代码块 ----------
    # 围栏代码块由 ``` 开头和结尾，中间内容保持原样
    code_blocks: List[str] = []
    processed_lines: List[str] = []
    in_code_block = False
    code_block_lines: List[str] = []
    code_lang = ""

    for line in lines:
        if not in_code_block:
            # 检测围栏代码块开始：``` 或 ```language
            match = re.match(r'^```(\w*)$', line)
            if match:
                in_code_block = True
                code_lang = match.group(1) or ""
                code_block_lines = []
            else:
                processed_lines.append(line)
        else:
            # 检测围栏代码块结束
            if line.strip() == '```':
                # 将代码块内容整体存储，使用占位符
                placeholder = f"<!--CODEBLOCK_{len(code_blocks)}-->"
                code_content = '\n'.join(code_block_lines)
                # 代码块内部的 HTML 实体需要反转义，保持原始内容
                code_content = unescape_html(code_content)
                code_blocks.append((code_lang, code_content))
                processed_lines.append(placeholder)
                in_code_block = False
            else:
                code_block_lines.append(line)

    # 如果文件以未闭合的代码块结束，也记录
    if in_code_block:
        placeholder = f"<!--CODEBLOCK_{len(code_blocks)}-->"
        code_content = '\n'.join(code_block_lines)
        code_content = unescape_html(code_content)
        code_blocks.append((code_lang, code_content))
        processed_lines.append(placeholder)

    # ---------- 第3步：对非代码块内容转义 HTML ----------
    escaped_lines = []
    for line in processed_lines:
        if re.match(r'^<!--CODEBLOCK_\d+-->$', line):
            escaped_lines.append(line)
        else:
            escaped_lines.append(escape_html(line))

    processed_lines = escaped_lines

    # ---------- 第4步：按空行分割为段落块 ----------
    # 每个段落块由连续的非空行组成
    blocks: List[List[str]] = []
    current_block: List[str] = []

    for line in processed_lines:
        if line.strip() == "":
            if current_block:
                blocks.append(current_block)
                current_block = []
        else:
            current_block.append(line)

    if current_block:
        blocks.append(current_block)

    # ---------- 第5步：转换每个段落块 ----------
    html_blocks: List[str] = []

    for block in blocks:
        first_line = block[0]

        # --- 检测代码块占位符 ---
        codeblock_match = re.match(r'^<!--CODEBLOCK_(\d+)-->$', first_line)
        if codeblock_match:
            idx = int(codeblock_match.group(1))
            lang, content = code_blocks[idx]
            # 为代码块添加语言类名（便于语法高亮），并对内容转义
            lang_attr = f' class="language-{lang}"' if lang else ''
            escaped_content = escape_html(content)
            html_block = f'<pre><code{lang_attr}>{escaped_content}</code></pre>'
            html_blocks.append(html_block)
            continue

        # --- 检测标题 ---
        header_match = re.match(r'^(#{1,6})\s+(.+)$', first_line)
        if header_match and len(block) == 1:
            level = len(header_match.group(1))
            content = header_match.group(2)
            content = convert_inline_formatting(content)
            html_blocks.append(f'<h{level}>{content}</h{level}>')
            continue

        # --- 检测水平线 ---
        if re.match(r'^[-*_]{3,}$', first_line.strip()) and len(block) == 1:
            html_blocks.append('<hr>')
            continue

        # --- 检测引用块 ---
        if first_line.startswith('>'):
            quoted_lines = []
            for bline in block:
                if bline.startswith('>'):
                    # 移除 > 前缀（保留一个空格如果有的话）
                    inner = bline[1:]
                    if inner.startswith(' '):
                        inner = inner[1:]
                    quoted_lines.append(inner)
                else:
                    quoted_lines.append(bline)
            quoted_text = '<br>\n'.join(
                convert_inline_formatting(l) for l in quoted_lines
            )
            html_blocks.append(f'<blockquote>\n{quoted_text}\n</blockquote>')
            continue

        # --- 检测无序列表 ---
        # 列表项：以 - 或 * 或 + 开头，后跟空格
        if all(re.match(r'^[-*+]\s+', l) for l in block):
            items = []
            for bline in block:
                item_content = re.sub(r'^[-*+]\s+', '', bline)
                item_content = convert_inline_formatting(item_content)
                items.append(f'<li>{item_content}</li>')
            html_blocks.append('<ul>\n' + '\n'.join(items) + '\n</ul>')
            continue

        # --- 检测有序列表 ---
        # 列表项：以 数字. 开头
        if all(re.match(r'^\d+\.\s+', l) for l in block):
            items = []
            for bline in block:
                item_content = re.sub(r'^\d+\.\s+', '', bline)
                item_content = convert_inline_formatting(item_content)
                items.append(f'<li>{item_content}</li>')
            html_blocks.append('<ol>\n' + '\n'.join(items) + '\n</ol>')
            continue

        # --- 普通段落 ---
        paragraph = ' '.join(block)
        paragraph = convert_inline_formatting(paragraph)
        html_blocks.append(f'<p>{paragraph}</p>')

    # ---------- 第6步：组装完整 HTML 文档 ----------
    body_content = '\n\n'.join(html_blocks)

    html_document = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Markdown 转换结果</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                         Roboto, "Helvetica Neue", Arial, sans-serif;
            max-width: 800px;
            margin: 40px auto;
            padding: 0 20px;
            line-height: 1.7;
            color: #333;
            background: #fff;
        }}
        h1, h2, h3, h4, h5, h6 {{
            margin-top: 1.5em;
            margin-bottom: 0.5em;
            font-weight: 600;
            color: #1a1a1a;
        }}
        h1 {{ font-size: 2em; border-bottom: 2px solid #eee; padding-bottom: 0.3em; }}
        h2 {{ font-size: 1.5em; border-bottom: 1px solid #eee; padding-bottom: 0.25em; }}
        h3 {{ font-size: 1.25em; }}
        h4 {{ font-size: 1em; }}
        p {{ margin: 1em 0; }}
        ul, ol {{ padding-left: 2em; margin: 1em 0; }}
        li {{ margin: 0.25em 0; }}
        strong {{ font-weight: 600; }}
        em {{ font-style: italic; }}
        a {{ color: #0366d6; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        img {{ max-width: 100%; height: auto; }}
        blockquote {{
            margin: 1em 0;
            padding: 0.5em 1em;
            border-left: 4px solid #dfe2e5;
            color: #6a737d;
            background: #f6f8fa;
        }}
        pre {{
            background: #f6f8fa;
            border: 1px solid #e1e4e8;
            border-radius: 6px;
            padding: 16px;
            overflow-x: auto;
        }}
        code {{
            font-family: "SFMono-Regular", Consolas, "Liberation Mono",
                         Menlo, Courier, monospace;
            font-size: 0.9em;
        }}
        pre code {{
            background: none;
            padding: 0;
        }}
        :not(pre) > code {{
            background: #f6f8fa;
            padding: 0.2em 0.4em;
            border-radius: 3px;
            color: #e83e8c;
        }}
        hr {{
            border: none;
            border-top: 2px solid #e1e4e8;
            margin: 2em 0;
        }}
    </style>
</head>
<body>
{body_content}
</body>
</html>"""

    return html_document


def read_markdown_file(filepath: str) -> str:
    """
    读取 Markdown 文件内容。

    Args:
        filepath: 文件路径

    Returns:
        文件内容字符串

    Raises:
        FileNotFoundError: 文件不存在
        PermissionError: 无读取权限
        IsADirectoryError: 路径是目录而非文件
        UnicodeDecodeError: 文件编码不是 UTF-8
    """
    # 检查路径是否存在
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"文件不存在: {filepath}")

    # 检查是否为目录
    if os.path.isdir(filepath):
        raise IsADirectoryError(f"路径是一个目录，而非文件: {filepath}")

    # 检查是否可读
    if not os.access(filepath, os.R_OK):
        raise PermissionError(f"没有读取权限: {filepath}")

    # 读取文件
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    return content


def write_html_file(filepath: str, content: str) -> None:
    """
    将 HTML 内容写入文件。

    Args:
        filepath: 输出文件路径
        content: HTML 内容字符串

    Raises:
        PermissionError: 无写入权限或目录不可写
        OSError: 其他 I/O 错误
    """
    # 确保输出目录存在
    output_dir = os.path.dirname(filepath)
    if output_dir and not os.path.exists(output_dir):
        try:
            os.makedirs(output_dir, exist_ok=True)
        except PermissionError:
            raise PermissionError(f"无法创建输出目录: {output_dir}")

    # 如果文件已存在，检查是否可写
    if os.path.exists(filepath) and not os.access(filepath, os.W_OK):
        raise PermissionError(f"没有写入权限: {filepath}")

    # 写入文件
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)


def main():
    """
    程序入口函数。

    解析命令行参数，读取 Markdown 文件，转换为 HTML 并输出。
    """
    parser = argparse.ArgumentParser(
        description="将 Markdown 文件转换为 HTML 文件",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    %(prog)s README.md
    %(prog)s README.md -o docs/index.html
    %(prog)s note.md --output output/note.html
        """
    )

    parser.add_argument(
        'input',
        type=str,
        help='输入的 Markdown 文件路径'
    )

    parser.add_argument(
        '-o', '--output',
        type=str,
        default=None,
        help='输出的 HTML 文件路径（默认：输入文件同目录下的 output.html）'
    )

    args = parser.parse_args()

    # ---------- 确定输入路径 ----------
    input_path = args.input

    # ---------- 确定输出路径 ----------
    if args.output:
        output_path = args.output
    else:
        # 默认输出：输入文件所在目录下的 output.html
        input_dir = os.path.dirname(os.path.abspath(input_path))
        output_path = os.path.join(input_dir, 'output.html')

    # ---------- 处理输入文件扩展名 ----------
    # 如果用户指定了非 .md 文件，给出提示但仍继续处理
    if not input_path.lower().endswith(('.md', '.markdown', '.mdown', '.mkd')):
        logger.warning(f"[WARN] 警告: 输入文件扩展名不是常见的 Markdown 扩展名，将继续处理。")

    # ---------- 读取、转换、写入 ----------
    try:
        logger.info(f"[READ] 正在读取: {input_path}")
        markdown_content = read_markdown_file(input_path)
        logger.info(f"   ✓ 读取成功 ({len(markdown_content)} 字符)")

        logger.info(f"[CONVERT] 正在转换 Markdown → HTML ...")
        html_content = convert_markdown_to_html(markdown_content)
        logger.info(f"   ✓ 转换完成 ({len(html_content)} 字符)")

        logger.info(f"[WRITE] 正在写入: {output_path}")
        write_html_file(output_path, html_content)
        logger.info(f"   ✓ 写入成功")

        # 显示输出文件大小
        file_size = os.path.getsize(output_path)
        if file_size < 1024:
            size_str = f"{file_size} B"
        elif file_size < 1024 * 1024:
            size_str = f"{file_size / 1024:.1f} KB"
        else:
            size_str = f"{file_size / (1024 * 1024):.1f} MB"

        logger.info(f"\n[DONE] 转换完成！")
        logger.info(f"   输入: {os.path.abspath(input_path)}")
        logger.info(f"   输出: {os.path.abspath(output_path)} ({size_str})")

    except FileNotFoundError as e:
        logger.error(f"[FAIL] 错误: {e}")
        sys.exit(1)

    except IsADirectoryError as e:
        logger.error(f"[FAIL] 错误: {e}")
        logger.error(f"   请指定一个 Markdown 文件而非目录。")
        sys.exit(1)

    except PermissionError as e:
        logger.error(f"[FAIL] 错误: {e}")
        logger.error(f"   请检查文件权限后重试。")
        sys.exit(1)

    except UnicodeDecodeError as e:
        logger.error(f"[FAIL] 错误: 无法以 UTF-8 编码读取文件。")
        logger.error(f"   详细信息: {e}")
        logger.error(f"   请确保文件使用 UTF-8 编码保存。")
        sys.exit(1)

    except OSError as e:
        logger.error(f"[FAIL] I/O 错误: {e}")
        sys.exit(1)

    except Exception as e:
        logger.error(f"[FAIL] 未知错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
