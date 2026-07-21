"""OpenClaw 适配器层的错误类型。"""


class OpenClawAdapterError(Exception):
    """OpenClaw 集成失败的基类错误。"""


class AdapterInitializationError(OpenClawAdapterError):
    """适配器引导启动失败时抛出。"""


class AdapterValidationError(OpenClawAdapterError):
    """适配器输入校验失败时抛出。"""


class AdapterOperationError(OpenClawAdapterError):
    """适配器操作无法完成时抛出。"""
