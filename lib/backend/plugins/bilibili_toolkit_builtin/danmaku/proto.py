"""B 站弹幕 protobuf 消息定义与解析。

B 站 ``/x/v2/dm/wbi/web/seg.so`` 接口返回 ``DmSegMobileReply`` 消息的
protobuf 二进制序列化结果，其中包含 ``repeated DanmakuElem elems`` 字段。
本模块通过 ``descriptor_pool`` + ``message_factory`` 在运行时构造 Message
类，无需 ``.proto`` 文件与 ``protoc`` 编译。

字段定义参考：
- ``bili-sync/crates/bili_sync/src/bilibili/danmaku/model.rs`` 的
  ``DanmakuElem`` 与 ``DmSegMobileReply``
- B 站官方 ``dm.proto`` 定义（tag 与字段类型完全一致）

与 Rust 参考实现的差异：
- 字段 ``mid_hash`` 在本实现中命名为 ``mid``，protobuf wire format 一致
  （tag=6, type=string），仅 Python 端属性名不同
- ``dmid_str`` / ``attr`` 字段保留以便扩展，但本阶段渲染层不使用
"""

from __future__ import annotations

from typing import Any

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from google.protobuf.message import Message as _ProtoMessage

# 字段标签：proto3 中标量字段默认为 optional（无 presence 语义）
_LABEL_OPTIONAL: int = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
_LABEL_REPEATED: int = descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED

# protobuf 字段类型常量简写
_TYPE_INT32: int = descriptor_pb2.FieldDescriptorProto.TYPE_INT32
_TYPE_INT64: int = descriptor_pb2.FieldDescriptorProto.TYPE_INT64
_TYPE_UINT32: int = descriptor_pb2.FieldDescriptorProto.TYPE_UINT32
_TYPE_STRING: int = descriptor_pb2.FieldDescriptorProto.TYPE_STRING
_TYPE_MESSAGE: int = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE

# 消息全名（含 package 前缀），用于从 DescriptorPool 检索
_DANMAKU_ELEM_FULL_NAME: str = "bilibili.danmaku.DanmakuElem"
_DM_SEG_REPLY_FULL_NAME: str = "bilibili.danmaku.DmSegMobileReply"


def _get_message_class(descriptor: Any) -> type[_ProtoMessage]:
    """兼容多版本 protobuf 地获取 Message 类。

    ``message_factory.GetMessageClass`` 在 protobuf 4.x 起作为顶层函数存在，
    但在部分 5.x / 6.x 发行版中曾被短暂移除或改名；旧版本（<4.0）则需要通过
    ``MessageFactory().GetPrototype(descriptor)`` 获取。这里用 ``getattr``
    动态探测，保证在 4.x / 5.x / 6.x 与旧版本上都能正常工作。

    Args:
        descriptor: ``DescriptorPool.FindMessageTypeByName`` 返回的消息描述符。

    Returns:
        与描述符对应的 protobuf Message 子类。
    """
    # 优先使用顶层 GetMessageClass（protobuf 4.x+ 推荐入口）
    get_class = getattr(message_factory, "GetMessageClass", None)
    if get_class is not None:
        return get_class(descriptor)
    # fallback: 旧版本 protobuf 通过 MessageFactory.GetPrototype 获取
    return message_factory.MessageFactory().GetPrototype(descriptor)


def _build_danmaku_message_class() -> type[_ProtoMessage]:
    """在模块加载时构造 DanmakuElem 与 DmSegMobileReply protobuf Message 类。

    通过 :class:`descriptor_pool.DescriptorPool` 动态注册 ``.proto`` 描述符，
    再用 :func:`_get_message_class` 创建对应的 Python Message 类（兼容多版本
    protobuf）。整个过程在 import 时完成一次，后续直接复用类对象。

    Returns:
        DanmakuElem 的 Message 子类。
    """
    file_descriptor = descriptor_pb2.FileDescriptorProto()
    file_descriptor.name = "bilibili_danmaku.proto"
    file_descriptor.package = "bilibili.danmaku"
    file_descriptor.syntax = "proto3"

    # DanmakuElem 消息定义
    elem_msg = file_descriptor.message_type.add()
    elem_msg.name = "DanmakuElem"
    _add_field(elem_msg, "id", 1, _TYPE_INT64, _LABEL_OPTIONAL)
    _add_field(elem_msg, "progress", 2, _TYPE_INT32, _LABEL_OPTIONAL)
    _add_field(elem_msg, "mode", 3, _TYPE_INT32, _LABEL_OPTIONAL)
    _add_field(elem_msg, "fontsize", 4, _TYPE_INT32, _LABEL_OPTIONAL)
    _add_field(elem_msg, "color", 5, _TYPE_UINT32, _LABEL_OPTIONAL)
    _add_field(elem_msg, "mid", 6, _TYPE_STRING, _LABEL_OPTIONAL)
    _add_field(elem_msg, "content", 7, _TYPE_STRING, _LABEL_OPTIONAL)
    _add_field(elem_msg, "ctime", 8, _TYPE_INT64, _LABEL_OPTIONAL)
    _add_field(elem_msg, "weight", 9, _TYPE_INT32, _LABEL_OPTIONAL)
    _add_field(elem_msg, "action", 10, _TYPE_STRING, _LABEL_OPTIONAL)
    _add_field(elem_msg, "pool", 11, _TYPE_INT32, _LABEL_OPTIONAL)
    _add_field(elem_msg, "dmid_str", 12, _TYPE_STRING, _LABEL_OPTIONAL)
    _add_field(elem_msg, "attr", 13, _TYPE_INT32, _LABEL_OPTIONAL)

    # DmSegMobileReply 消息定义（含 repeated DanmakuElem elems 字段）
    reply_msg = file_descriptor.message_type.add()
    reply_msg.name = "DmSegMobileReply"
    elems_field = reply_msg.field.add()
    elems_field.name = "elems"
    elems_field.number = 1
    elems_field.type = _TYPE_MESSAGE
    elems_field.label = _LABEL_REPEATED
    elems_field.type_name = f".{_DANMAKU_ELEM_FULL_NAME}"

    pool = descriptor_pool.DescriptorPool()
    pool.Add(file_descriptor)
    elem_desc = pool.FindMessageTypeByName(_DANMAKU_ELEM_FULL_NAME)
    reply_desc = pool.FindMessageTypeByName(_DM_SEG_REPLY_FULL_NAME)

    # 同时构造两个类，DmSegMobileReply 类挂在模块级变量上以便解析使用
    global _DmSegMobileReplyClass
    _DmSegMobileReplyClass = _get_message_class(reply_desc)
    return _get_message_class(elem_desc)


def _add_field(
    msg_desc: Any,
    name: str,
    number: int,
    field_type: int,
    label: int,
) -> None:
    """向消息描述符追加一个字段定义。

    Args:
        msg_desc: ``FileDescriptorProto.message_type[i]`` 对应的 DescriptorProto。
        name: 字段名。
        number: 字段 tag number。
        field_type: protobuf 字段类型常量。
        label: 字段标签（OPTIONAL / REPEATED）。
    """
    field = msg_desc.field.add()
    field.name = name
    field.number = number
    field.type = field_type
    field.label = label


# 模块加载时构造 DanmakuElem 类
DanmakuElem: type[_ProtoMessage] = _build_danmaku_message_class()

# DmSegMobileReply 类在 _build_danmaku_message_class 中赋值，类型注解便于静态检查
_DmSegMobileReplyClass: type[_ProtoMessage]  # type: ignore[assignment]


def parse_danmaku_segs(raw_bytes: bytes) -> list[_ProtoMessage]:
    """解析 ``/x/v2/dm/wbi/web/seg.so`` 端点的 protobuf 响应为 DanmakuElem 列表。

    响应体是 ``DmSegMobileReply`` 消息的 protobuf 序列化结果，
    ``elems`` 字段为 ``repeated DanmakuElem``。

    Args:
        raw_bytes: HTTP 响应体原始字节。

    Returns:
        :class:`DanmakuElem` 实例列表。空响应（如该段无弹幕）返回空列表。
    """
    if not raw_bytes:
        return []
    reply = _DmSegMobileReplyClass()
    reply.ParseFromString(raw_bytes)
    return list(reply.elems)


__all__ = [
    "DanmakuElem",
    "parse_danmaku_segs",
]
