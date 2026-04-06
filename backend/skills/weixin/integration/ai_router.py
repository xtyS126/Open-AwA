"""
AI路由器模块
提供消息到AI引擎的路由、AI回复到微信的转换、流式回复处理等功能
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Awaitable, AsyncIterator

from loguru import logger

from skills.weixin.messaging.inbound import InboundMessage


@dataclass
class AIResponse:
    """
    AI响应数据类
    封装AI引擎返回的响应信息
    
    属性:
        text: 响应文本内容
        is_streaming: 是否为流式响应
        is_complete: 响应是否完成
        metadata: 响应元数据
        error: 错误信息
    """
    text: str = ""
    is_streaming: bool = False
    is_complete: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """
        将响应转换为字典格式
        
        返回:
            包含响应所有字段的字典
        """
        return {
            "text": self.text,
            "is_streaming": self.is_streaming,
            "is_complete": self.is_complete,
            "metadata": self.metadata,
            "error": self.error,
        }


@dataclass
class MessageContext:
    """
    消息上下文数据类
    封装消息处理的上下文信息
    
    属性:
        account_id: 账号ID
        user_id: 用户ID
        session_id: 会话ID
        context_token: 上下文令牌
        history: 历史消息列表
        metadata: 额外元数据
    """
    account_id: str = ""
    user_id: str = ""
    session_id: str = ""
    context_token: str = ""
    history: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class AIRouter:
    """
    AI路由器类
    负责将微信消息路由到AI引擎，并将AI响应转换为微信消息格式
    
    属性:
        engine_type: AI引擎类型
        model: 使用的模型名称
        max_tokens: 最大生成token数
        temperature: 生成温度
        stream_enabled: 是否启用流式响应
    """
    
    def __init__(
        self,
        engine_type: str = "openai",
        model: str = "gpt-4",
        max_tokens: int = 2000,
        temperature: float = 0.7,
        stream_enabled: bool = False,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
    ):
        """
        初始化AI路由器
        
        参数:
            engine_type: AI引擎类型（openai/anthropic/custom）
            model: 使用的模型名称
            max_tokens: 最大生成token数
            temperature: 生成温度（0-1）
            stream_enabled: 是否启用流式响应
            api_key: API密钥
            api_base: API基础URL
        """
        self.engine_type = engine_type
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.stream_enabled = stream_enabled
        self.api_key = api_key
        self.api_base = api_base
        
        self._client: Optional[Any] = None
        self._preprocessors: List[Callable[[str, MessageContext], Awaitable[str]]] = []
        self._postprocessors: List[Callable[[AIResponse, MessageContext], Awaitable[AIResponse]]] = []
        self._system_prompt: str = self._default_system_prompt()
    
    def _default_system_prompt(self) -> str:
        """
        获取默认系统提示词
        
        返回:
            默认系统提示词字符串
        """
        return (
            "你是一个智能助手，通过微信与用户交流。"
            "请用简洁、友好的方式回复用户消息。"
            "如果用户发送的是图片或其他媒体，请根据内容进行回复。"
        )
    
    def set_system_prompt(self, prompt: str) -> None:
        """
        设置系统提示词
        
        参数:
            prompt: 系统提示词内容
        """
        self._system_prompt = prompt
    
    def add_preprocessor(
        self,
        processor: Callable[[str, MessageContext], Awaitable[str]],
    ) -> None:
        """
        添加消息预处理器
        
        参数:
            processor: 预处理函数，接收消息文本和上下文，返回处理后的文本
        """
        self._preprocessors.append(processor)
    
    def add_postprocessor(
        self,
        processor: Callable[[AIResponse, MessageContext], Awaitable[AIResponse]],
    ) -> None:
        """
        添加响应后处理器
        
        参数:
            processor: 后处理函数，接收响应和上下文，返回处理后的响应
        """
        self._postprocessors.append(processor)
    
    async def _preprocess_message(
        self,
        text: str,
        context: MessageContext,
    ) -> str:
        """
        预处理消息文本
        
        参数:
            text: 原始消息文本
            context: 消息上下文
            
        返回:
            处理后的消息文本
        """
        processed = text
        for processor in self._preprocessors:
            try:
                processed = await processor(processed, context)
            except Exception as exc:
                logger.warning(f"Preprocessor error: {exc}")
        return processed
    
    async def _postprocess_response(
        self,
        response: AIResponse,
        context: MessageContext,
    ) -> AIResponse:
        """
        后处理AI响应
        
        参数:
            response: 原始AI响应
            context: 消息上下文
            
        返回:
            处理后的AI响应
        """
        processed = response
        for processor in self._postprocessors:
            try:
                processed = await processor(processed, context)
            except Exception as exc:
                logger.warning(f"Postprocessor error: {exc}")
        return processed
    
    def _build_context(self, message: InboundMessage) -> MessageContext:
        """
        从入站消息构建上下文
        
        参数:
            message: 入站消息
            
        返回:
            MessageContext实例
        """
        return MessageContext(
            account_id=message.to_user_id,
            user_id=message.from_user_id,
            session_id=message.session_id,
            context_token=message.context_token,
            metadata={
                "message_id": message.message_id,
                "seq": message.seq,
                "create_time_ms": message.create_time_ms,
            },
        )
    
    async def route_message(self, message: InboundMessage) -> str:
        """
        将消息路由到AI引擎并获取响应
        
        参数:
            message: 入站消息
            
        返回:
            AI响应文本
        """
        context = self._build_context(message)
        
        processed_text = await self._preprocess_message(message.text, context)
        
        if not processed_text.strip():
            return ""
        
        try:
            response = await self._call_ai_engine(processed_text, context)
            
            response = await self._postprocess_response(response, context)
            
            if response.error:
                logger.error(f"AI engine error: {response.error}")
                return f"AI处理出错: {response.error}"
            
            return response.text
            
        except Exception as exc:
            logger.error(f"Route message error: {exc}")
            return f"消息处理失败: {str(exc)}"
    
    async def _call_ai_engine(
        self,
        text: str,
        context: MessageContext,
    ) -> AIResponse:
        """
        调用AI引擎
        
        参数:
            text: 输入文本
            context: 消息上下文
            
        返回:
            AIResponse实例
        """
        if self.engine_type == "openai":
            return await self._call_openai(text, context)
        elif self.engine_type == "anthropic":
            return await self._call_anthropic(text, context)
        elif self.engine_type == "mock":
            return await self._call_mock(text, context)
        else:
            return AIResponse(
                text="",
                error=f"不支持的AI引擎类型: {self.engine_type}",
            )
    
    async def _call_openai(
        self,
        text: str,
        context: MessageContext,
    ) -> AIResponse:
        """
        调用OpenAI API
        
        参数:
            text: 输入文本
            context: 消息上下文
            
        返回:
            AIResponse实例
        """
        try:
            import openai
            
            client = openai.AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.api_base,
            )
            
            messages = [
                {"role": "system", "content": self._system_prompt},
            ]
            
            for hist in context.history[-10:]:
                messages.append(hist)
            
            messages.append({"role": "user", "content": text})
            
            if self.stream_enabled:
                return await self._stream_openai_response(client, messages, context)
            
            response = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
            )
            
            content = response.choices[0].message.content or ""
            
            return AIResponse(
                text=content,
                is_streaming=False,
                is_complete=True,
                metadata={
                    "model": response.model,
                    "usage": {
                        "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                        "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                    },
                },
            )
            
        except ImportError:
            return AIResponse(text="", error="openai库未安装，请运行 pip install openai")
        except Exception as exc:
            return AIResponse(text="", error=str(exc))
    
    async def _stream_openai_response(
        self,
        client: Any,
        messages: List[Dict[str, str]],
        context: MessageContext,
    ) -> AIResponse:
        """
        流式获取OpenAI响应
        
        参数:
            client: OpenAI客户端
            messages: 消息列表
            context: 消息上下文
            
        返回:
            AIResponse实例（包含完整文本）
        """
        try:
            stream = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                stream=True,
            )
            
            full_content = ""
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    full_content += chunk.choices[0].delta.content
            
            return AIResponse(
                text=full_content,
                is_streaming=True,
                is_complete=True,
                metadata={"streamed": True},
            )
            
        except Exception as exc:
            return AIResponse(text="", error=str(exc))
    
    async def _call_anthropic(
        self,
        text: str,
        context: MessageContext,
    ) -> AIResponse:
        """
        调用Anthropic API
        
        参数:
            text: 输入文本
            context: 消息上下文
            
        返回:
            AIResponse实例
        """
        try:
            import anthropic
            
            client = anthropic.AsyncAnthropic(api_key=self.api_key)
            
            messages = []
            for hist in context.history[-10:]:
                messages.append(hist)
            messages.append({"role": "user", "content": text})
            
            response = await client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self._system_prompt,
                messages=messages,
            )
            
            content = ""
            for block in response.content:
                if hasattr(block, "text"):
                    content += block.text
            
            return AIResponse(
                text=content,
                is_streaming=False,
                is_complete=True,
                metadata={
                    "model": response.model,
                    "usage": {
                        "input_tokens": response.usage.input_tokens,
                        "output_tokens": response.usage.output_tokens,
                    },
                },
            )
            
        except ImportError:
            return AIResponse(text="", error="anthropic库未安装，请运行 pip install anthropic")
        except Exception as exc:
            return AIResponse(text="", error=str(exc))
    
    async def _call_mock(
        self,
        text: str,
        context: MessageContext,
    ) -> AIResponse:
        """
        模拟AI响应（用于测试）
        
        参数:
            text: 输入文本
            context: 消息上下文
            
        返回:
            AIResponse实例
        """
        await asyncio.sleep(0.1)
        
        return AIResponse(
            text=f"[Mock回复] 收到您的消息: {text[:100]}",
            is_streaming=False,
            is_complete=True,
            metadata={"mock": True},
        )
    
    async def process_ai_response(
        self,
        response: str,
        context: Dict[str, Any],
    ) -> List[str]:
        """
        处理AI响应，转换为适合微信发送的消息列表
        
        参数:
            response: AI响应文本
            context: 处理上下文
            
        返回:
            处理后的消息列表（可能被分割为多条）
        """
        if not response:
            return []
        
        processed = self._markdown_to_plain_text(response)
        
        max_length = context.get("max_length", 4000)
        
        messages = self._split_message(processed, max_length)
        
        return messages
    
    def _markdown_to_plain_text(self, text: str) -> str:
        """
        将Markdown转换为纯文本
        
        参数:
            text: Markdown文本
            
        返回:
            纯文本
        """
        result = text
        
        result = re.sub(r"```[^\n]*\n?([\s\S]*?)```", r"\n\1\n", result)
        
        result = re.sub(r"`([^`]+)`", r"\1", result)
        
        result = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", result)
        
        result = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", result)
        
        result = re.sub(r"^\|[\s:|-]+\|$", "", result, flags=re.MULTILINE)
        
        result = re.sub(r"^#{1,6}\s+", "", result, flags=re.MULTILINE)
        
        result = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", result)
        result = re.sub(r"_{1,2}([^_]+)_{1,2}", r"\1", result)
        
        result = re.sub(r"\n{3,}", "\n\n", result)
        result = result.strip()
        
        return result
    
    def _split_message(self, text: str, max_length: int) -> List[str]:
        """
        分割长消息为多条短消息
        
        参数:
            text: 原始文本
            max_length: 单条消息最大长度
            
        返回:
            分割后的消息列表
        """
        if len(text) <= max_length:
            return [text]
        
        messages: List[str] = []
        remaining = text
        
        while remaining:
            if len(remaining) <= max_length:
                messages.append(remaining)
                break
            
            split_pos = self._find_split_position(remaining, max_length)
            
            messages.append(remaining[:split_pos].strip())
            remaining = remaining[split_pos:].strip()
        
        return messages
    
    def _find_split_position(self, text: str, max_pos: int) -> int:
        """
        找到合适的分割位置
        
        参数:
            text: 文本
            max_pos: 最大位置
            
        返回:
            分割位置
        """
        search_text = text[:max_pos]
        
        for sep in ["\n\n", "\n", "。", "！", "？", ".", "!", "?", "；", ";", "，", ",", " "]:
            pos = search_text.rfind(sep)
            if pos > max_pos // 2:
                return pos + len(sep)
        
        return max_pos
    
    async def stream_response(
        self,
        message: InboundMessage,
        on_chunk: Callable[[str], Awaitable[None]],
    ) -> str:
        """
        流式处理AI响应
        
        参数:
            message: 入站消息
            on_chunk: 每个chunk的回调函数
            
        返回:
            完整的响应文本
        """
        context = self._build_context(message)
        processed_text = await self._preprocess_message(message.text, context)
        
        if not processed_text.strip():
            return ""
        
        full_response = ""
        
        try:
            async for chunk in self._stream_ai_response(processed_text, context):
                full_response += chunk
                await on_chunk(chunk)
            
            response = AIResponse(
                text=full_response,
                is_streaming=True,
                is_complete=True,
            )
            
            response = await self._postprocess_response(response, context)
            
            return response.text
            
        except Exception as exc:
            logger.error(f"Stream response error: {exc}")
            return f"流式响应失败: {str(exc)}"
    
    async def _stream_ai_response(
        self,
        text: str,
        context: MessageContext,
    ) -> AsyncIterator[str]:
        """
        流式获取AI响应
        
        参数:
            text: 输入文本
            context: 消息上下文
            
        生成:
            响应文本的chunk
        """
        if self.engine_type == "openai":
            async for chunk in self._stream_openai_chunks(text, context):
                yield chunk
        else:
            response = await self._call_ai_engine(text, context)
            if response.text:
                chunk_size = 10
                for i in range(0, len(response.text), chunk_size):
                    yield response.text[i:i + chunk_size]
                    await asyncio.sleep(0.01)
    
    async def _stream_openai_chunks(
        self,
        text: str,
        context: MessageContext,
    ) -> AsyncIterator[str]:
        """
        流式获取OpenAI响应chunks
        
        参数:
            text: 输入文本
            context: 消息上下文
            
        生成:
            响应文本的chunk
        """
        try:
            import openai
            
            client = openai.AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.api_base,
            )
            
            messages = [
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": text},
            ]
            
            stream = await client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                stream=True,
            )
            
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
                    
        except ImportError:
            yield "[错误] openai库未安装"
        except Exception as exc:
            yield f"[错误] {str(exc)}"
    
    def to_dict(self) -> Dict[str, Any]:
        """
        将路由器配置转换为字典
        
        返回:
            包含配置信息的字典
        """
        return {
            "engine_type": self.engine_type,
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "stream_enabled": self.stream_enabled,
            "api_base": self.api_base,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AIRouter:
        """
        从字典创建路由器实例
        
        参数:
            data: 包含配置信息的字典
            
        返回:
            AIRouter实例
        """
        return cls(
            engine_type=data.get("engine_type", "openai"),
            model=data.get("model", "gpt-4"),
            max_tokens=data.get("max_tokens", 2000),
            temperature=data.get("temperature", 0.7),
            stream_enabled=data.get("stream_enabled", False),
            api_key=data.get("api_key"),
            api_base=data.get("api_base"),
        )
