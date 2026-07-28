"""核心层端口抽象包。

存放领域核心层（core/*）对外部依赖（API 层、基础设施层）的抽象端口（Protocol）。
通过端口反转依赖方向，避免 core/* 直接 import api/routes/* 形成反向依赖。
具体适配器实现位于 api/adapters/，由 main.py 在 lifespan 启动时注入。
"""
