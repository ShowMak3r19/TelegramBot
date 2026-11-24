# Telebot

基于 Python 与 Telethon 的模块化 Telegram 机器人，提供由后端直接托管的 Web 管理后台。适合在个人电脑、Linux 服务器、NAS 或 Docker 环境中部署。

> ⚠️ **安全提示与免责声明（请务必阅读）**
>
> **本项目默认没有登录鉴权，仅适合个人在可信内网 / 局域网 / NAS 环境自用，严禁直接暴露到公网！**
> 管理后台可直接控制 Telegram 登录会话、收发消息与各项配置；虽然可选通过 `admin.username` / `admin.password`（或环境变量 `TGBOT_ADMIN_USERNAME` / `TGBOT_ADMIN_PASSWORD`）开启基础登录页，但本项目并非面向公网暴露的多租户安全系统。**因暴露公网、配置不当、未妥善保管会话/凭据文件或任何违规使用导致的账号异常、封禁、数据泄露或其他任何问题，均由使用者自行承担，项目作者一概不负责。**

## 功能

| 模块 | 说明 |
| --- | --- |
| 红包与口令 | 模板识别、自动领取、口令红包及趣味算术红包 |
| AI 对话 | 可配置触发条件、上下文和模型服务，支持 OpenAI 兼容与 Anthropic 接口 |
| AI 生图 | 文本或参考图片生成、尺寸与发送策略配置 |
| AI 解密 | 识别文本或图片题目，按模板调用 AI 作答 |
| 群友画像 | 根据群聊历史生成带原消息引用的娱乐性画像 |
| 自动签到 | Cron 定时发送、任务启停与执行状态 |
| 消息转发 | 回复消息后转发、复制文本、引用或生成消息链接 |
| 媒体工具 | GIF 截取转换、群聊词云、语录贴纸 |
| 聊天小游戏 | 幸运词、Emoji 图谜和乱码解码 |
| 聊天归档 | SQLite 文本归档、消息编辑同步与可选历史回填 |
| 管理后台 | 服务启停、模块配置、外观定制、侧栏编排、运行状态、日志和 AI 用量 |

所有功能模块默认关闭，配置后按需启用。部分指令要求由当前登录账号发送；具体触发词及参数可在后台查看和修改。

## Docker 部署（推荐）

仓库提供 `Dockerfile` 与 `docker-compose.yml`（预装 Python 3.11、FFmpeg、Tesseract OCR 以及中文/Emoji 字体），默认通过目录挂载 `./config:/app/config`、`./sessions:/app/sessions` 与 `./runtime:/app/runtime` 持久化数据。

```bash
git clone https://github.com/ShowMak3r19/TelegramBot.git
cd TelegramBot
mkdir -p config sessions runtime
cp config.example.json config/config.json
```

编辑 `config/config.json`，填入你自己的 Telegram `api_id`、`api_hash`（按需填写 `bot_token`）与监听群组并将 `telegram.enabled` 设为 `true`；AI 功能需另行填写模型服务地址、模型名与 API Key。

首次使用 Telegram 用户账号登录时，请先用交互式终端启动一次完成手机号/验证码/两步验证登录（已有 `sessions/*.session` 可跳过）：

```bash
docker compose run --rm -it telebot
# 登录成功并生成 sessions/*.session 后按 Ctrl+C 退出
```

随后以守护模式启动：

```bash
docker compose up -d --build
```

启动后在**内网**打开 `http://<宿主机或NAS内网IP>:8088`（默认映射 `8088:8088`；如仅限本机访问，可将 `docker-compose.yml` 的端口改为 `127.0.0.1:8088:8088`）。更多容器维护与代理参数见 [部署说明](docs/deployment.md)。

> ⚠️ **再次提醒**：Docker 默认配置**无登录鉴权**，仅适合自己内网使用，切勿将端口暴露到公网；出现任何问题一概不负责。

## 本地 Python 启动

推荐 Python 3.11。安装依赖并生成自己的配置：

```bash
git clone https://github.com/ShowMak3r19/TelegramBot.git
cd TelegramBot
python -m venv .venv
# Linux / macOS
source .venv/bin/activate
# Windows 使用 .venv\Scripts\activate
python -m pip install -r requirements.txt
python -m telegram_bot --init-config --config config.json
```

编辑 `config.json`：

1. 填写自己的 Telegram `api_id`、`api_hash`，按需填写 `bot_token`；用户账号首次登录时需要手机号、验证码及可能的两步验证密码。
2. 配置监听群 `telegram.monitored_groups`，将 `telegram.enabled` 设置为 `true`。
3. AI 功能需另行配置模型服务地址、模型名与 API Key。
4. 如需基础登录页，可自行设置 `admin.username` 与强密码 `admin.password`（默认留空即无登录鉴权）。

```bash
python -m telegram_bot --config config.json
```

首次 Telegram 登录请在交互式终端完成。直接运行 Python 时后台默认监听 `127.0.0.1:8088`；局域网访问可将 `admin.host` 改为 `0.0.0.0`，但请务必仅限个人内网使用。

GIF 等媒体功能需要系统安装 FFmpeg；OCR 需要 Tesseract；中文词云和图谜需要可用的中文字体。Docker 镜像与 Conda 部署文件已包含这些依赖。

## Linux / NAS Conda 部署

```bash
chmod +x nas-install-miniconda.sh nas-conda-setup.sh nas-conda-run.sh
./nas-install-miniconda.sh
./nas-conda-setup.sh
# 先编辑 config.json，填写自己的配置
./nas-conda-run.sh
```

已有 Conda 时可省略安装脚本。更新依赖后重新执行 `./nas-conda-setup.sh`，再重启服务。完整说明见 [部署说明](docs/deployment.md)。

## 配置与数据

- `config.example.json`：无凭据的默认配置参考；本地直接运行使用 `config.json`，Docker 部署默认使用 `config/config.json`。
- `sessions/`：Telegram 登录会话，具有账号访问权限，应严格保密。
- `runtime/`：数据库、状态、日志和生成文件；日志单文件 5 MB，最多保留 5 份。
- 支持 `TGBOT_CONFIG`、`TGBOT_ADMIN_HOST`、`TGBOT_ADMIN_PORT`、`TGBOT_ADMIN_USERNAME`、`TGBOT_ADMIN_PASSWORD`、`TGBOT_TELEGRAM_ENABLED`、`TGBOT_TELEGRAM_API_ID`、`TGBOT_TELEGRAM_API_HASH`、`TGBOT_TELEGRAM_BOT_TOKEN`、`TGBOT_LOG_LEVEL` 等环境变量。

聊天归档默认保存监听范围内的新消息文字；历史回填默认关闭。群友画像及 AI 功能会将处理所需内容发送至配置的模型服务。语录贴纸会将消息和头像交给配置的 quote-api 服务，可改用自建地址。请按自己的群聊和数据管理要求决定启用范围。

## 开发与测试

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

`telegram_bot/` 按应用、配置、Telegram 适配、模块、持久化、后台任务、共享服务与管理 UI 分层；`tests/` 包含单元及管理后台导航测试。开发约定见 [架构说明](docs/architecture.md)。

本仓库与下载包不包含运行凭据、登录会话、聊天数据库或运行日志。
