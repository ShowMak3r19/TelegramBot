# 架构与开发

- `app.py`：应用生命周期和依赖装配。
- `config.py`：类型化配置、文件加载和环境变量覆盖。
- `telegram/`：Telethon 接入和消息事件适配。
- `modules/`：模块注册、启停、消息处理与配置更新。
- `persistence/`、`jobs/`：聊天数据存储和后台回填任务。
- `shared/`：AI、媒体、网络与 Telegram 辅助适配。
- `admin/`：管理 API 与静态前端。

新模块应通过注册器和服务接口协作，避免修改无关模块。新增模块同时更新后台导航、视图映射、详情表单、图标信息和导航覆盖测试。

配置、登录会话、数据库和日志不提交到 Git。新增依赖须说明用途；`requirements-dev.txt` 中的 pytest 用于现有测试使用的标准夹具。验证使用 `python -m pytest -q`；前端修改同时检查 JavaScript 语法并在浏览器查看。
