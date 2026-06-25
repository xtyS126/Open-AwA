#!/usr/bin/env python3
"""
Markdown to HTML Converter
==========================
支持标准 Markdown 语法：
- 标题 (# ~ ######)
- 粗体/斜体
- 代码块和行内代码
- 有序/无序列表
- 链接和图片
- 引用块
- 水平分割线

用法:
  python md_to_html.py input.md -o output.html
  python md_to_html.py input.md --watch    # 监视模式
  python md_to_html.py input.md --github   # GitHub风格
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path

from loguru import logger


def escape_html(text: str) -> str:
    """转义HTML特殊字符"""
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    return text


def convert_markdown_to_html(markdown_text: str) -> str:
    """
    将 Markdown 文本转换为 HTML。
    按正确顺序处理各元素，避免冲突。
    """
    lines = markdown_text.split('\n')
    html_lines = []
    
    # 状态跟踪
    in_code_block = False
    code_block_lang = ''
    code_block_content = []
    in_ol = False      # 有序列表中
    in_ul = False      # 无序列表中
    in_blockquote = False
    in_paragraph = False
    paragraph_lines = []
    
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.rstrip()
        
        # --- 代码块 ---
        if stripped.startswith('```'):
            if in_code_block:
                # 关闭代码块
                lang_attr = f' class="language-{code_block_lang}"' if code_block_lang else ''
                code_html = f'<pre><code{lang_attr}>{escape_html(chr(10).join(code_block_content))}</code></pre>'
                html_lines.append(code_html)
                in_code_block = False
                code_block_lang = ''
                code_block_content = []
            else:
                # 开始代码块
                code_block_lang = stripped[3:].strip()
                in_code_block = True
            i += 1
            continue
        
        if in_code_block:
            code_block_content.append(stripped)
            i += 1
            continue
        
        # --- 空行 ---
        if stripped == '':
            # 关闭当前段落/列表/引用
            if in_paragraph:
                html_lines.append(f'<p>{" ".join(paragraph_lines)}</p>')
                paragraph_lines = []
                in_paragraph = False
            if in_ul:
                html_lines.append('</ul>')
                in_ul = False
            if in_ol:
                html_lines.append('</ol>')
                in_ol = False
            if in_blockquote:
                html_lines.append('</blockquote>')
                in_blockquote = False
            html_lines.append('')
            i += 1
            continue
        
        # --- 水平分割线 ---
        if re.match(r'^[-*_]{3,}\s*$', stripped):
            if in_paragraph:
                html_lines.append(f'<p>{" ".join(paragraph_lines)}</p>')
                paragraph_lines = []
                in_paragraph = False
            html_lines.append('<hr>')
            i += 1
            continue
        
        # --- 标题 ---
        header_match = re.match(r'^(#{1,6})\s+(.+?)(?:\s+#+)?$', stripped)
        if header_match:
            if in_paragraph:
                html_lines.append(f'<p>{" ".join(paragraph_lines)}</p>')
                paragraph_lines = []
                in_paragraph = False
            level = len(header_match.group(1))
            content = process_inline(header_match.group(2))
            html_lines.append(f'<h{level}>{content}</h{level}>')
            i += 1
            continue
        
        # --- 引用块 ---
        if stripped.startswith('> '):
            if in_paragraph:
                html_lines.append(f'<p>{" ".join(paragraph_lines)}</p>')
                paragraph_lines = []
                in_paragraph = False
            if not in_blockquote:
                html_lines.append('<blockquote>')
                in_blockquote = True
            quote_content = process_inline(stripped[2:])
            html_lines.append(f'<p>{quote_content}</p>')
            i += 1
            continue
        
        # --- 无序列表 ---
        ul_match = re.match(r'^[*\-+]\s+(.+)$', stripped)
        if ul_match:
            if in_paragraph:
                html_lines.append(f'<p>{" ".join(paragraph_lines)}</p>')
                paragraph_lines = []
                in_paragraph = False
            if in_ol:
                html_lines.append('</ol>')
                in_ol = False
            if not in_ul:
                html_lines.append('<ul>')
                in_ul = True
            content = process_inline(ul_match.group(1))
            html_lines.append(f'<li>{content}</li>')
            i += 1
            continue
        
        # --- 有序列表 ---
        ol_match = re.match(r'^\d+\.\s+(.+)$', stripped)
        if ol_match:
            if in_paragraph:
                html_lines.append(f'<p>{" ".join(paragraph_lines)}</p>')
                paragraph_lines = []
                in_paragraph = False
            if in_ul:
                html_lines.append('</ul>')
                in_ul = False
            if not in_ol:
                html_lines.append('<ol>')
                in_ol = True
            content = process_inline(ol_match.group(1))
            html_lines.append(f'<li>{content}</li>')
            i += 1
            continue
        
        # --- 普通段落 ---
        processed = process_inline(stripped)
        paragraph_lines.append(processed)
        in_paragraph = True
        i += 1
    
    # 关闭所有未关闭的标签
    if in_paragraph:
        html_lines.append(f'<p>{" ".join(paragraph_lines)}</p>')
    if in_ul:
        html_lines.append('</ul>')
    if in_ol:
        html_lines.append('</ol>')
    if in_blockquote:
        html_lines.append('</blockquote>')
    
    return '\n'.join(html_lines)


def process_inline(text: str) -> str:
    """处理行内元素（需按正确顺序）"""
    # 1. 保护行内代码（优先处理，避免内部语法被转换）
    code_placeholders = {}
    
    def protect_code(m):
        idx = len(code_placeholders)
        placeholder = f'%%CODE_{idx}%%'
        code_placeholders[placeholder] = f'<code>{escape_html(m.group(1))}</code>'
        return placeholder
    
    text = re.sub(r'`([^`]+)`', protect_code, text)
    
    # 2. 图片（先于链接处理）
    text = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', r'<img src="\2" alt="\1">', text)
    
    # 3. 链接
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
    
    # 4. 粗体+斜体（***或___）
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<strong><em>\1</em></strong>', text)
    text = re.sub(r'___(.+?)___', r'<strong><em>\1</em></strong>', text)
    
    # 5. 粗体
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'__(.+?)__', r'<strong>\1</strong>', text)
    
    # 6. 斜体
    text = re.sub(r'\*([^*\n]+)\*', r'<em>\1</em>', text)
    text = re.sub(r'_([^_\n]+)_', r'<em>\1</em>', text)
    
    # 7. 删除线
    text = re.sub(r'~~(.+?)~~', r'<del>\1</del>', text)
    
    # 8. 恢复代码占位符
    for placeholder, code_html in code_placeholders.items():
        text = text.replace(placeholder, code_html)
    
    return text


def wrap_html(body: str, title: str = '', style: str = 'default') -> str:
    """生成完整的HTML文档"""
    css_map = {
        'default': '''
        body { max-width: 800px; margin: 0 auto; padding: 20px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; line-height: 1.6; color: #333; }
        h1, h2, h3, h4, h5, h6 { margin-top: 1.5em; margin-bottom: 0.5em; color: #1a1a1a; }
        h1 { border-bottom: 2px solid #eee; padding-bottom: 0.3em; }
        h2 { border-bottom: 1px solid #eee; padding-bottom: 0.3em; }
        code { background: #f4f4f4; padding: 2px 6px; border-radius: 3px; font-size: 0.9em; }
        pre { background: #f8f8f8; padding: 16px; border-radius: 6px; overflow-x: auto; }
        pre code { background: none; padding: 0; }
        blockquote { border-left: 4px solid #ddd; margin: 0; padding: 0 16px; color: #666; }
        table { border-collapse: collapse; width: 100%; }
        th, td { border: 1px solid #ddd; padding: 8px 12px; text-align: left; }
        th { background: #f4f4f4; }
        ''',
        'github': '''
        body { max-width: 800px; margin: 0 auto; padding: 45px; font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif,"Apple Color Emoji","Segoe UI Emoji"; font-size: 16px; line-height: 1.5; color: #24292e; background: #fff; }
        h1, h2 { border-bottom: 1px solid #eaecef; padding-bottom: 0.3em; }
        code { background: rgba(27,31,35,0.05); padding: 0.2em 0.4em; border-radius: 3px; font-size: 85%; }
        pre { background: #f6f8fa; padding: 16px; border-radius: 6px; }
        pre code { background: none; padding: 0; font-size: 85%; }
        blockquote { border-left: 0.25em solid #dfe2e5; padding: 0 1em; color: #6a737d; }
        table tr:nth-child(2n) { background: #f6f8fa; }
        img { max-width: 100%; }
        '''
    }
    
    css = css_map.get(style, css_map['default'])
    title_tag = f'<title>{title}</title>' if title else ''
    
    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
{title_tag}
<style>{css}</style>
</head>
<body>
{body}
</body>
</html>'''


def convert_file(input_path: str, output_path: str = None, style: str = 'default', standalone: bool = True) -> str:
    """
    转换Markdown文件为HTML
    
    返回值: 输出文件路径
    """
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"输入文件不存在: {input_path}")
    
    if output_path is None:
        output_path = input_path.with_suffix('.html')
    else:
        output_path = Path(output_path)
    
    md_content = input_path.read_text(encoding='utf-8')
    body = convert_markdown_to_html(md_content)
    
    if standalone:
        title = input_path.stem
        html = wrap_html(body, title=title, style=style)
    else:
        html = body
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding='utf-8')
    
    return str(output_path)


def watch_mode(input_path: str, output_path: str = None, style: str = 'default'):
    """监视模式：文件变化时自动转换"""
    from pathlib import Path
    input_path = Path(input_path)
    last_mtime = input_path.stat().st_mtime if input_path.exists() else 0
    
    logger.info(f"[WATCH] 监视模式已启动: {input_path}")
    logger.info("   按 Ctrl+C 退出")
    
    try:
        while True:
            if input_path.exists():
                current_mtime = input_path.stat().st_mtime
                if current_mtime > last_mtime:
                    last_mtime = current_mtime
                    try:
                        out = convert_file(str(input_path), output_path, style)
                        logger.info(f"[DONE] 已转换: {input_path} → {out} ({time.strftime('%H:%M:%S')})")
                    except Exception as e:
                        logger.error(f"[FAIL] 转换失败: {e}")
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("\n[EXIT] 监视模式已退出")


def main():
    parser = argparse.ArgumentParser(
        description='Markdown 转 HTML 转换器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
  %(prog)s README.md                     # 转为 README.html
  %(prog)s input.md -o output.html       # 指定输出路径
  %(prog)s input.md --github             # GitHub风格
  %(prog)s input.md --no-standalone      # 仅输出body内容
  %(prog)s input.md --watch              # 监视文件变化
        '''
    )
    parser.add_argument('input', help='输入的 Markdown 文件路径')
    parser.add_argument('-o', '--output', help='输出的 HTML 文件路径（默认替换扩展名为 .html）')
    parser.add_argument('--github', action='store_true', help='使用 GitHub 风格样式')
    parser.add_argument('--dark', action='store_true', help='使用深色主题（简版）')
    parser.add_argument('--no-standalone', action='store_true', help='仅输出 HTML body，不生成完整文档')
    parser.add_argument('--watch', '-w', action='store_true', help='监视文件变化，自动重新转换')
    parser.add_argument('--body-only', action='store_true', help='同 --no-standalone')
    
    args = parser.parse_args()
    
    style = 'github' if args.github else 'default'
    
    if args.watch:
        watch_mode(args.input, args.output, style)
        return
    
    standalone = not (args.no_standalone or args.body_only)
    
    try:
        output_path = convert_file(args.input, args.output, style, standalone)
        logger.info(f"[DONE] 转换完成: {output_path}")
    except Exception as e:
        logger.error(f"[FAIL] 错误: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
