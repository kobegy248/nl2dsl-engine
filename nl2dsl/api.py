"""正式生产入口（薄封装）。

整个项目唯一的 app 创建方式是 :func:`nl2dsl.api_factory.create_app`。
本模块仅做两件事：

1. 调用 ``create_app()`` 构建正式 app（复用 Engine 真实 DomainContext，
   含 RAG / Optimizer / 权限 / 审计 / 数据库 FeedbackStore）。
2. 暴露模块级 ``app`` 供 ``uvicorn nl2dsl.api:app`` 与 ``from nl2dsl.api import app``
   使用，确保生产入口与测试创建的 app 走同一实现，不再维护两套路由 / 请求模型 /
   反馈逻辑。

如需自定义注入（mock 数据库、自定义 registry 等），测试应直接调用
``nl2dsl.api_factory.create_app(...)``，而不是修改本文件。
"""

from __future__ import annotations

from nl2dsl.api_factory import create_app

app = create_app()
