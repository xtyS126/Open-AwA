"""API 层适配器包。

存放 core.ports.* 端口的 API 层具体实现（适配器）。
适配器将领域核心层的端口调用委托给 api/routes/* 中的具体函数，
由 main.py 在 lifespan 启动时构造并注入到领域核心层。
"""
