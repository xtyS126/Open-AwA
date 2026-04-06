"""
消息格式转换模块
提供 Markdown 到纯文本的转换功能
"""

from __future__ import annotations

import re
from typing import List, Tuple


def strip_code_blocks(text: str) -> str:
    """
    去除代码块标记，保留代码内容
    
    参数:
        text: 包含代码块的文本
        
    返回:
        去除代码块标记后的文本
    """
    if not text:
        return ""
    
    pattern = r'```[^\n]*\n?([\s\S]*?)```'
    
    def replace_code_block(match: re.Match) -> str:
        code_content = match.group(1)
        return code_content.rstrip('\n')
    
    result = re.sub(pattern, replace_code_block, text)
    
    return result


def strip_inline_code(text: str) -> str:
    """
    去除行内代码标记，保留代码内容
    
    参数:
        text: 包含行内代码的文本
        
    返回:
        去除行内代码标记后的文本
    """
    if not text:
        return ""
    
    result = re.sub(r'`([^`]+)`', r'\1', text)
    
    return result


def strip_links(text: str) -> str:
    """
    去除链接标记，保留显示文本
    
    参数:
        text: 包含链接的文本
        
    返回:
        去除链接标记后的文本
    """
    if not text:
        return ""
    
    result = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    
    return result


def strip_images(text: str) -> str:
    """
    去除图片标记
    
    参数:
        text: 包含图片的文本
        
    返回:
        去除图片标记后的文本
    """
    if not text:
        return ""
    
    result = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)
    
    return result


def strip_tables(text: str) -> str:
    """
    转换表格为简单文本格式
    
    参数:
        text: 包含表格的文本
        
    返回:
        转换后的文本
    """
    if not text:
        return ""
    
    result = re.sub(r'^\|[\s:|-]+\|$', '', text, flags=re.MULTILINE)
    
    lines = result.split('\n')
    processed_lines: List[str] = []
    
    for line in lines:
        if '|' in line and line.strip().startswith('|'):
            cells = [cell.strip() for cell in line.strip('|').split('|')]
            processed_line = ' | '.join(cells)
            processed_lines.append(processed_line)
        else:
            processed_lines.append(line)
    
    return '\n'.join(processed_lines)


def strip_headers(text: str) -> str:
    """
    去除标题标记，保留标题文本
    
    参数:
        text: 包含标题的文本
        
    返回:
        去除标题标记后的文本
    """
    if not text:
        return ""
    
    result = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    
    return result


def strip_bold(text: str) -> str:
    """
    去除粗体标记，保留文本内容
    
    参数:
        text: 包含粗体的文本
        
    返回:
        去除粗体标记后的文本
    """
    if not text:
        return ""
    
    result = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    result = re.sub(r'__([^_]+)__', r'\1', result)
    
    return result


def strip_italic(text: str) -> str:
    """
    去除斜体标记，保留文本内容
    
    参数:
        text: 包含斜体的文本
        
    返回:
        去除斜体标记后的文本
    """
    if not text:
        return ""
    
    result = re.sub(r'\*([^*]+)\*', r'\1', text)
    result = re.sub(r'_([^_]+)_', r'\1', result)
    
    return result


def strip_strikethrough(text: str) -> str:
    """
    去除删除线标记，保留文本内容
    
    参数:
        text: 包含删除线的文本
        
    返回:
        去除删除线标记后的文本
    """
    if not text:
        return ""
    
    result = re.sub(r'~~([^~]+)~~', r'\1', text)
    
    return result


def strip_blockquotes(text: str) -> str:
    """
    去除引用标记，保留引用内容
    
    参数:
        text: 包含引用的文本
        
    返回:
        去除引用标记后的文本
    """
    if not text:
        return ""
    
    result = re.sub(r'^>\s*', '', text, flags=re.MULTILINE)
    
    return result


def strip_horizontal_rules(text: str) -> str:
    """
    去除水平分割线
    
    参数:
        text: 包含水平分割线的文本
        
    返回:
        去除水平分割线后的文本
    """
    if not text:
        return ""
    
    result = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)
    
    return result


def convert_lists(text: str) -> str:
    """
    转换列表格式为纯文本
    
    参数:
        text: 包含列表的文本
        
    返回:
        转换后的文本
    """
    if not text:
        return ""
    
    result = re.sub(r'^[\*\-\+]\s+', '- ', text, flags=re.MULTILINE)
    
    result = re.sub(r'^\d+\.\s+', '- ', result, flags=re.MULTILINE)
    
    return result


def strip_html_tags(text: str) -> str:
    """
    去除HTML标签，保留内容
    
    参数:
        text: 包含HTML标签的文本
        
    返回:
        去除HTML标签后的文本
    """
    if not text:
        return ""
    
    result = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    
    result = re.sub(r'<[^>]+>', '', result)
    
    return result


def normalize_whitespace(text: str) -> str:
    """
    规范化空白字符
    
    参数:
        text: 待处理的文本
        
    返回:
        规范化后的文本
    """
    if not text:
        return ""
    
    result = re.sub(r'[ \t]+', ' ', text)
    
    result = re.sub(r'\n{3,}', '\n\n', result)
    
    lines = result.split('\n')
    processed_lines = [line.rstrip() for line in lines]
    result = '\n'.join(processed_lines)
    
    return result.strip()


def markdown_to_plain_text(text: str) -> str:
    """
    将 Markdown 转换为纯文本
    
    参数:
        text: Markdown 格式的文本
        
    返回:
        转换后的纯文本
    """
    if not text:
        return ""
    
    result = text
    
    result = strip_code_blocks(result)
    
    result = strip_images(result)
    
    result = strip_links(result)
    
    result = strip_tables(result)
    
    result = strip_headers(result)
    
    result = strip_bold(result)
    
    result = strip_italic(result)
    
    result = strip_strikethrough(result)
    
    result = strip_inline_code(result)
    
    result = strip_blockquotes(result)
    
    result = strip_horizontal_rules(result)
    
    result = convert_lists(result)
    
    result = strip_html_tags(result)
    
    result = normalize_whitespace(result)
    
    return result


def split_message(text: str, max_length: int = 4000) -> List[str]:
    """
    将消息分割为多个块，每块不超过指定长度
    
    参数:
        text: 待分割的文本
        max_length: 每块最大长度，默认4000字符
        
    返回:
        分割后的文本块列表
    """
    if not text:
        return []
    
    if len(text) <= max_length:
        return [text]
    
    chunks: List[str] = []
    
    paragraphs = text.split('\n\n')
    current_chunk = ""
    
    for paragraph in paragraphs:
        if not paragraph.strip():
            continue
        
        if len(current_chunk) + len(paragraph) + 2 <= max_length:
            if current_chunk:
                current_chunk += '\n\n' + paragraph
            else:
                current_chunk = paragraph
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            
            if len(paragraph) <= max_length:
                current_chunk = paragraph
            else:
                sub_chunks = _split_long_paragraph(paragraph, max_length)
                chunks.extend(sub_chunks[:-1])
                current_chunk = sub_chunks[-1] if sub_chunks else ""
    
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
    
    return chunks


def _split_long_paragraph(paragraph: str, max_length: int) -> List[str]:
    """
    分割过长的段落
    
    参数:
        paragraph: 待分割的段落
        max_length: 每块最大长度
        
    返回:
        分割后的文本块列表
    """
    if len(paragraph) <= max_length:
        return [paragraph]
    
    chunks: List[str] = []
    lines = paragraph.split('\n')
    current_chunk = ""
    
    for line in lines:
        if len(current_chunk) + len(line) + 1 <= max_length:
            if current_chunk:
                current_chunk += '\n' + line
            else:
                current_chunk = line
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            
            if len(line) <= max_length:
                current_chunk = line
            else:
                sub_chunks = _split_long_line(line, max_length)
                chunks.extend(sub_chunks[:-1])
                current_chunk = sub_chunks[-1] if sub_chunks else ""
    
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
    
    return chunks


def _split_long_line(line: str, max_length: int) -> List[str]:
    """
    分割过长的行
    
    参数:
        line: 待分割的行
        max_length: 每块最大长度
        
    返回:
        分割后的文本块列表
    """
    if len(line) <= max_length:
        return [line]
    
    chunks: List[str] = []
    
    sentences = re.split(r'([。！？.!?])', line)
    
    current_chunk = ""
    i = 0
    while i < len(sentences):
        sentence = sentences[i]
        if i + 1 < len(sentences) and re.match(r'[。！？.!?]', sentences[i + 1]):
            sentence += sentences[i + 1]
            i += 1
        
        if len(current_chunk) + len(sentence) <= max_length:
            current_chunk += sentence
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            
            if len(sentence) <= max_length:
                current_chunk = sentence
            else:
                for j in range(0, len(sentence), max_length):
                    chunk = sentence[j:j + max_length]
                    chunks.append(chunk)
                current_chunk = ""
        
        i += 1
    
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
    
    return chunks


def truncate_message(text: str, max_length: int = 4000, suffix: str = "...") -> str:
    """
    截断消息到指定长度
    
    参数:
        text: 待截断的文本
        max_length: 最大长度
        suffix: 截断后缀
        
    返回:
        截断后的文本
    """
    if not text or len(text) <= max_length:
        return text
    
    truncate_at = max_length - len(suffix)
    
    last_newline = text.rfind('\n', 0, truncate_at)
    if last_newline > truncate_at * 0.5:
        return text[:last_newline].rstrip() + suffix
    
    last_space = text.rfind(' ', 0, truncate_at)
    if last_space > truncate_at * 0.5:
        return text[:last_space].rstrip() + suffix
    
    return text[:truncate_at] + suffix


def estimate_message_parts(text: str, max_length: int = 4000) -> int:
    """
    估算消息分割后的部分数量
    
    参数:
        text: 待估算的文本
        max_length: 每块最大长度
        
    返回:
        预估的部分数量
    """
    if not text:
        return 0
    
    if len(text) <= max_length:
        return 1
    
    chunks = split_message(text, max_length)
    return len(chunks)


def format_code_for_weixin(code: str, language: str = "") -> str:
    """
    格式化代码以便在微信中显示
    
    参数:
        code: 代码内容
        language: 编程语言（可选）
        
    返回:
        格式化后的代码文本
    """
    if not code:
        return ""
    
    lines = code.strip().split('\n')
    
    min_indent = float('inf')
    for line in lines:
        if line.strip():
            indent = len(line) - len(line.lstrip())
            min_indent = min(min_indent, indent)
    
    if min_indent > 0 and min_indent != float('inf'):
        lines = [line[min_indent:] if len(line) >= min_indent else line.lstrip() for line in lines]
    
    result = '\n'.join(lines)
    
    return result


def escape_special_chars(text: str) -> str:
    """
    转义微信特殊字符
    
    参数:
        text: 待转义的文本
        
    返回:
        转义后的文本
    """
    if not text:
        return ""
    
    result = text
    
    return result
