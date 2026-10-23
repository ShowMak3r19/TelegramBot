# 部署说明

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

备份 `config.json`、`sessions/` 和所需 `runtime/` 数据，使用受限权限保存，避免上传到代码仓库。升级前停止服务并备份 SQLite 文件。远程访问管理页时配置鉴权，并通过可信反向代理提供 HTTPS。

发布默认绑定 `127.0.0.1`，默认不连接 Telegram。仓库不包含已验证的 Docker 镜像或容器部署文件。
