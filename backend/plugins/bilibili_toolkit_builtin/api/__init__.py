"""bilibili-toolkit-builtin 内置插件 API 路由包。

阶段 15 实现：暴露订阅管理、视频列表、下载任务触发与查询、
配置读写等 REST 接口，前缀 ``/api/plugins/bilibili-toolkit-builtin``。

路由由 ``main.py`` 统一注册，插件自身不挂载到 app。
"""
