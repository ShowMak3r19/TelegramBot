# 部署说明

> ⚠️ **安全提示与免责声明（必读）**
>
> **本项目默认没有登录鉴权，仅适合个人在可信内网 / 局域网 / NAS 环境自用，严禁直接暴露到公网！**
> 后台拥有控制 Telegram 账号会话与修改配置的权限。即便可选配置了基础用户名/密码，本项目也未针对公网暴露做完整安全加固。**任何因公网暴露、端口映射不当或违规使用造成的账号封禁、数据泄露及其他一切问题，项目作者概不负责。**

## Docker Compose 部署（推荐）

镜像基于 `python:3.11-slim`，内置 FFmpeg、Tesseract OCR（含简体中文与英文语言包）及中文/Emoji 字体。

### 1. 准备目录与配置

```bash
mkdir -p config sessions runtime
cp config.example.json config/config.json
```

编辑 `config/config.json` 填入 Telegram 凭据与监听群组。

> 请保持 `./config:/app/config` **目录挂载**，不要改成单文件挂载 `./config.json:/app/config.json`，否则后台保存配置执行原子替换时可能触发 Docker `Device or resource busy` 错误。

### 2. 首次交互登录 Telegram（用户号）

如果还没有现成的 `sessions/*.session` 登录态，先交互运行一次完成手机号/验证码登录：

```bash
docker compose run --rm -it telebot
```

登录成功后再按 `Ctrl+C` 停止临时容器，会话文件已保存在 `./sessions/` 中。

### 3. 启动与维护

```bash
# 构建并后台启动
docker compose up -d --build

# 查看日志
docker compose logs -f telebot

# 更新代码后重建
docker compose up -d --build

# 停止并移除容器（数据保留在 ./config、./sessions、./runtime）
docker compose down
```

- 默认端口映射为 `8088:8088`，内网访问 `http://<宿主机或NAS内网IP>:8088`。如仅本机访问，可改为 `127.0.0.1:8088:8088`。
- 如需代理，可在 `docker-compose.yml` 的 `environment` 中取消 `HTTP_PROXY` / `HTTPS_PROXY` 注释并填写代理地址。
- 容器内已配置健康检查（探活 `/api/auth`），可通过 `docker ps` 查看健康状态。

## Linux / systemd 部署

建议将项目放到 `/opt/telegrambot`，创建独立服务用户并给予项目目录写权限；也可自行选择目录。先用交互式终端启动一次，完成 Telegram 登录，再配置后台服务。

仓库的 `deploy/telegrambot.service` 是通用模板。将文件中的 `User`、`Group`、`WorkingDirectory`、`ExecStart` 和配置路径改成自己的实际值。示例使用项目内的 `.venv`；Conda 用户可将 `ExecStart` 改为 `/bin/bash /实际目录/nas-conda-run.sh`。

```bash
sudo cp deploy/telegrambot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now telegrambot
sudo systemctl status telegrambot --no-pager
sudo journalctl -u telegrambot -n 100 --no-pager
```

更新源码或依赖后使用 `sudo systemctl restart telegrambot`。NAS 不支持 systemd 时，使用系统提供的进程管理器运行同一启动命令；网络挂载目录需在服务启动前就绪。

## 备份与安全注意事项

- 备份 `config.json`（或 `config/config.json`）、`sessions/` 和所需 `runtime/` 数据，使用受限权限保存，避免上传到代码仓库。
- 升级前停止服务并备份 SQLite 文件（`runtime/data/chat_history.sqlite3`）。
- 再次强调：**本服务默认无登录鉴权，仅限个人内网环境使用，严禁公网裸奔，出现问题一概不负责。**
