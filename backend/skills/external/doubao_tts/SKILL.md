---
name: doubao-tts
description: 豆包语音合成与声音复刻 Skill，集成火山引擎 Doubao-Seed-TTS 2.0 和 ICL 2.0
---

# 豆包 TTS 语音合成与声音复刻 Skill

## 概述

`doubao-tts` 是 Open-AwA 的语音合成与声音复刻技能，基于火山引擎豆包语音大模型（Doubao-Seed-TTS 2.0 / ICL 2.0），支持：

- **语音合成（TTS）**：文本转语音，支持流式和非流式两种模式，数十种预置音色 + 复刻音色
- **声音复刻（Voice Cloning）**：上传 14~30 秒音频样本，训练专属音色
- **音色管理**：查询、试听、删除已复刻的音色

### 核心特性

- 流式音频合成：基于 SSE 协议实时推送音频块，首帧延迟低至 200ms
- 情感表达控制：通过自然语言指令或参数控制情感（高兴/悲伤/愤怒等）
- 上下文文本（Context Texts）：提供上下文提升情感演绎准确度
- 多语种支持：中文、英文、日语、西班牙语、印尼语等
- SSML 标记语言：精确控制发音、停顿、韵律
- 异步长文本合成：最大支持 10 万字符，适合播客/有声书场景

## 目录结构

```
backend/skills/external/doubao-tts/
├── SKILL.md                      # 本文档
├── skill.yaml                    # Skill 元数据
└── core/
    ├── __init__.py               # 公共 API 导出
    ├── models.py                 # Pydantic 数据模型
    ├── tts_client.py             # Doubao TTS API 客户端
    └── voice_clone.py            # 声音复刻管理
```

## 配置

在环境变量或 `.env` 文件中配置火山引擎 API 凭证：

| 变量 | 说明 | 必填 |
|------|------|------|
| `DOUBAO_APP_ID` | 火山引擎应用 ID | 是 |
| `DOUBAO_ACCESS_KEY` | 火山引擎 Access Key | 是 |
| `DOUBAO_TTS_RESOURCE_ID` | TTS 资源 ID（默认 `seed-tts-2.0`） | 否 |
| `DOUBAO_ICL_RESOURCE_ID` | 声音复刻资源 ID（默认 `seed-icl-2.0`） | 否 |

在火山引擎控制台开通"豆包语音合成模型 2.0"和"豆包声音复刻模型 2.0"服务后获取凭证。

## 使用示例

### TTS 合成（非流式）

```python
from skills.external.doubao_tts.core import DoubaoTTSService, TTSRequest

client = DoubaoTTSService(app_id="xxx", access_key="xxx")
audio_bytes = await client.synthesize("你好，欢迎使用 Open-AwA！", speaker_id="default")
with open("output.mp3", "wb") as f:
    f.write(audio_bytes)
```

### TTS 流式合成

```python
async for chunk in client.synthesize_stream("这是一段流式合成的文本。", speaker_id="default"):
    # chunk 为音频字节块，可实时推送到前端
    yield chunk
```

### 声音复刻

```python
from skills.external.doubao_tts.core import VoiceCloneManager

manager = VoiceCloneManager(app_id="xxx", access_key="xxx")
speaker_id = await manager.create_speaker(
    audio_bytes=open("sample.wav", "rb").read(),
    voice_name="我的声音",
    context_texts="这是用于训练的声音样本。",
)
print(f"复刻成功，speaker_id: {speaker_id}")
```

## 参数说明

### TTS 合成参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `text` | string | - | 要合成的文本内容 |
| `speaker_id` | string | `default` | 音色 ID（预置或复刻） |
| `audio_format` | string | `mp3` | 音频格式：mp3 / wav / pcm / ogg_opus |
| `sample_rate` | int | 24000 | 采样率（Hz） |
| `speed_ratio` | float | 1.0 | 语速倍率（0.5 ~ 2.0） |
| `volume_ratio` | float | 1.0 | 音量倍率（0.1 ~ 3.0） |
| `pitch_ratio` | float | 0.0 | 音调偏移（-12 ~ 12 半音） |
| `emotion` | string | - | 情感类型：happy / sad / angry / fearful / surprised / neutral |
| `emotion_scale` | float | 1.0 | 情感强度（1 ~ 5） |
| `context_texts` | string | - | 上下文文本，与合成内容语义相关，提升情感表达 |
| `language` | string | `zh` | 语言代码：zh / en / ja / es / id / pt / de / fr |

### 声音复刻要求

- 音频格式：WAV
- 时长：14 ~ 30 秒
- 质量要求：低噪声、单人声、单轨音频
- 情绪一致性：不忽高忽低，保持稳定风格
- 中英混场景需同时覆盖中英文

## 与前端集成

前端 TTS 页面位于 `frontend/src/features/tts/`，提供：
- 文本输入 → 参数调节 → 一键合成
- 音色库浏览与试听
- 声音复刻向导（上传 → 训练 → 预览）

## 参考

- 火山引擎豆包语音文档：https://www.volcengine.com/docs/6561
- 声音复刻最佳实践：https://www.volcengine.com/docs/6561/2298705
