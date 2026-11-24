from __future__ import annotations

import base64
import binascii
import hmac
import json
import logging
import mimetypes
import secrets
import threading
import urllib.parse
from http.cookies import SimpleCookie
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from telegram_bot.admin.ui_preferences import (
    MAX_SKIN_BODY_BYTES,
    MAX_WALLPAPER_BODY_BYTES,
    delete_skin,
    delete_uploaded_wallpaper,
    export_mvskin_bytes,
    import_mvskin_base64,
    load_ui_preferences,
    resolve_skin_asset,
    resolve_skins_dir,
    resolve_ui_paths,
    resolve_wallpaper_file,
    save_ui_preferences,
    save_uploaded_wallpaper,
    update_skin_meta,
)
from telegram_bot.logging_setup import list_log_files, read_log_tail

logger = logging.getLogger(__name__)

SESSION_COOKIE_NAME = "telegrambot_admin_session"
_MAX_BODY_BYTES = 2 * 1024 * 1024
_MAX_SESSION_TOKENS = 256


def _safe_next_url(raw: str) -> str:
    candidate = str(raw or "").strip()
    if not candidate or not candidate.startswith("/") or candidate.startswith(("//", "/\\")):
        return "/"
    parsed = urllib.parse.urlsplit(candidate)
    if parsed.scheme or parsed.netloc:
        return "/"
    return candidate


def _admin_auth_enabled(admin: Any) -> bool:
    return bool(str(getattr(admin, "username", "") or "")) and bool(str(getattr(admin, "password", "") or ""))


def _credentials_ok(username: str, password: str, expected_username: str, expected_password: str) -> bool:
    return hmac.compare_digest(str(username), str(expected_username)) and hmac.compare_digest(str(password), str(expected_password))


def _basic_auth_ok(header: str, username: str, password: str) -> bool:
    if not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header[6:].strip(), validate=True).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return False
    user, sep, pwd = decoded.partition(":")
    if not sep:
        return False
    return _credentials_ok(user, pwd, username, password)


def _cookie_value(header: str, name: str) -> str:
    if not header:
        return ""
    cookie = SimpleCookie()
    try:
        cookie.load(header)
    except Exception:
        return ""
    morsel = cookie.get(name)
    return morsel.value if morsel is not None else ""


def _session_auth_ok(cookie_header: str, active_tokens: set[str]) -> bool:
    token = _cookie_value(cookie_header, SESSION_COOKIE_NAME)
    return bool(token and token in active_tokens)


def _new_session_token() -> str:
    return secrets.token_urlsafe(32)


def _session_cookie(token: str) -> str:
    return f"{SESSION_COOKIE_NAME}={token}; Path=/; Max-Age=31536000; HttpOnly; SameSite=Lax"


def _clear_session_cookie() -> str:
    return f"{SESSION_COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"


class AdminServer:
    def __init__(self, app: Any) -> None:
        self.app = app
        self.httpd: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.session_tokens: set[str] = set()

    def start(self) -> None:
        handler = self._handler_class()
        host = self.app.config.admin.host
        port = int(self.app.config.admin.port)
        self.httpd = ThreadingHTTPServer((host, port), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="admin-http", daemon=True)
        self.thread.start()
        if _admin_auth_enabled(self.app.config.admin):
            logger.info("Admin UI listening on http://%s:%s (Auth enabled)", host, port)
        else:
            logger.warning(
                "Admin UI listening on http://%s:%s WITHOUT auth; set admin.username/password "
                "(or TGBOT_ADMIN_USERNAME/PASSWORD) to protect it.",
                host,
                port,
            )

    def stop(self) -> None:
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
        logger.info("Admin UI stopped")

    def _handler_class(self) -> type[BaseHTTPRequestHandler]:
        app = self.app
        static_dir = Path(__file__).resolve().parent / "static"
        session_tokens = self.session_tokens

        class Handler(BaseHTTPRequestHandler):
            server_version = "TelegramBotAdmin/0.1"

            def do_GET(self) -> None:
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path == "/login":
                    self._serve_login(parsed)
                    return
                if parsed.path in {"/assets/telegrambot-logo.png", "/assets/favicon-32.png"}:
                    self._serve_static(parsed.path, static_dir)
                    return
                if parsed.path == "/api/auth":
                    self._json({"authenticated": self._is_authenticated(), "auth_enabled": _admin_auth_enabled(app.config.admin)})
                    return
                if not self._require_auth(parsed.path):
                    return
                if parsed.path.startswith("/api/"):
                    self._handle_api_get(parsed)
                    return
                self._serve_static(parsed.path, static_dir)

            def do_POST(self) -> None:
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path == "/api/login":
                    self._handle_login()
                    return
                if parsed.path == "/api/logout":
                    self._handle_logout()
                    return
                if not self._require_auth(parsed.path):
                    return
                if parsed.path.startswith("/api/"):
                    if not self._same_origin_ok():
                        self._json({"ok": False, "error": "cross-origin request blocked"}, HTTPStatus.FORBIDDEN)
                        return
                    self._handle_api_post(parsed)
                    return
                self.send_error(HTTPStatus.NOT_FOUND)

            def do_PUT(self) -> None:
                parsed = urllib.parse.urlparse(self.path)
                if not self._require_auth(parsed.path):
                    return
                if parsed.path.startswith("/api/"):
                    if not self._same_origin_ok():
                        self._json({"ok": False, "error": "cross-origin request blocked"}, HTTPStatus.FORBIDDEN)
                        return
                    self._handle_api_put(parsed)
                    return
                self.send_error(HTTPStatus.NOT_FOUND)

            def _same_origin_ok(self) -> bool:
                origin = (self.headers.get("Origin") or "").strip()
                if not origin:
                    return True
                host = (self.headers.get("Host") or "").strip().lower()
                if not host:
                    return True
                parsed_origin = urllib.parse.urlsplit(origin)
                return bool(parsed_origin.netloc) and parsed_origin.netloc.lower() == host

            def _require_auth(self, path: str) -> bool:
                if not _admin_auth_enabled(app.config.admin):
                    return True
                if self._is_authenticated():
                    return True
                if _basic_auth_ok(
                    self.headers.get("Authorization", ""),
                    app.config.admin.username,
                    app.config.admin.password,
                ):
                    return True
                if self.command == "GET" and not path.startswith("/api/"):
                    self._redirect(f"/login?next={urllib.parse.quote(self.path or '/', safe='')}")
                    return False
                self._json({"error": "login required"}, HTTPStatus.UNAUTHORIZED)
                return False

            def _is_authenticated(self) -> bool:
                if not _admin_auth_enabled(app.config.admin):
                    return True
                return _session_auth_ok(self.headers.get("Cookie", ""), session_tokens)

            def _handle_login(self) -> None:
                if not _admin_auth_enabled(app.config.admin):
                    self._json({"ok": True, "auth_enabled": False})
                    return
                try:
                    body = self._body_json()
                except ValueError as exc:
                    self._json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
                    return
                username = str(body.get("username") or "")
                password = str(body.get("password") or "")
                if not _credentials_ok(username, password, app.config.admin.username, app.config.admin.password):
                    self._json({"ok": False, "error": "invalid credentials"}, HTTPStatus.UNAUTHORIZED)
                    return
                token = _new_session_token()
                if len(session_tokens) >= _MAX_SESSION_TOKENS:
                    session_tokens.clear()
                session_tokens.add(token)
                self._json({"ok": True}, headers={"Set-Cookie": _session_cookie(token)})

            def _handle_logout(self) -> None:
                token = _cookie_value(self.headers.get("Cookie", ""), SESSION_COOKIE_NAME)
                if token:
                    session_tokens.discard(token)
                self._json({"ok": True}, headers={"Set-Cookie": _clear_session_cookie()})

            def _serve_login(self, parsed: urllib.parse.ParseResult) -> None:
                if self._is_authenticated():
                    self._redirect("/")
                    return
                query = urllib.parse.parse_qs(parsed.query)
                next_url = _safe_next_url(query.get("next", ["/"])[0])
                data = _login_page(next_url).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-cache, must-revalidate")
                self.send_header("Pragma", "no-cache")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _redirect(self, target: str) -> None:
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", target)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, fmt: str, *args: Any) -> None:
                logger.debug("admin-http " + fmt, *args)

            def _handle_api_get(self, parsed: urllib.parse.ParseResult) -> None:
                query = urllib.parse.parse_qs(parsed.query)
                if parsed.path == "/api/status":
                    self._json(app.status_snapshot())
                elif parsed.path == "/api/modules":
                    self._json({"modules": app.modules.cards()})
                elif parsed.path == "/api/modules/export":
                    raw_ids = query.get("modules", [])
                    selected: list[str] | None = None
                    if raw_ids:
                        selected = [item.strip() for part in raw_ids for item in part.split(",") if item.strip()]
                    try:
                        self._json(app.export_modules_config(selected))
                    except ValueError as exc:
                        self._json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
                elif parsed.path.startswith("/api/modules/"):
                    module_id = parsed.path.rsplit("/", 1)[-1]
                    module = app.modules.get(module_id)
                    if not module:
                        self.send_error(HTTPStatus.NOT_FOUND)
                        return
                    self._json(module.card.__dict__)
                elif parsed.path == "/api/ai":
                    self._json(app.ai_snapshot())
                elif parsed.path == "/api/ai/usage":
                    range_key = query.get("range", ["today"])[0]
                    self._json(app.ai_usage_snapshot(range_key))
                elif parsed.path == "/api/settings":
                    self._json(app.settings_snapshot())
                elif parsed.path == "/api/groups":
                    try:
                        self._json({"groups": app.list_groups()})
                    except RuntimeError as exc:
                        logger.warning("Cannot list Telegram groups: %s", exc)
                        self._json({"groups": [], "error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE)
                    except Exception as exc:
                        logger.exception("Failed to list Telegram groups")
                        self._json({"groups": [], "error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE)
                elif parsed.path == "/api/telegram-targets":
                    try:
                        self._json({"targets": app.list_targets()})
                    except RuntimeError as exc:
                        logger.warning("Cannot list Telegram targets: %s", exc)
                        self._json({"targets": [], "error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE)
                    except Exception as exc:
                        logger.exception("Failed to list Telegram targets")
                        self._json({"targets": [], "error": str(exc)}, HTTPStatus.SERVICE_UNAVAILABLE)
                elif parsed.path == "/api/logs/recent":
                    self._json({"records": app.recent_logs.tail(200)})
                elif parsed.path == "/api/logs/files":
                    self._json({"files": list_log_files(app.config.logs, app.project_root)})
                elif parsed.path == "/api/logs/read":
                    name = query.get("file", [app.config.logs.file_name])[0]
                    try:
                        lines = max(1, min(int(query.get("lines", ["300"])[0]), 10_000))
                    except ValueError:
                        self._json({"error": "invalid lines parameter"}, HTTPStatus.BAD_REQUEST)
                        return
                    try:
                        self._json({"name": name, "content": read_log_tail(app.config.logs, app.project_root, name, lines)})
                    except (FileNotFoundError, ValueError):
                        self.send_error(HTTPStatus.NOT_FOUND)
                elif parsed.path == "/api/logs/download":
                    name = query.get("file", [app.config.logs.file_name])[0]
                    self._download_log(name)
                elif parsed.path == "/api/ui/preferences":
                    prefs_path, wallpapers_dir = resolve_ui_paths(app)
                    self._json(load_ui_preferences(prefs_path, wallpapers_dir))
                elif parsed.path.startswith("/api/ui/wallpapers/"):
                    name = urllib.parse.unquote(parsed.path.rsplit("/", 1)[-1])
                    self._serve_wallpaper(name)
                elif parsed.path.startswith("/api/ui/skins/"):
                    parts = [urllib.parse.unquote(seg) for seg in parsed.path[len("/api/ui/skins/"):].split("/") if seg]
                    if len(parts) == 2 and parts[1] in {"background", "avatar"}:
                        self._serve_skin_asset(parts[0], parts[1])
                    elif len(parts) == 2 and parts[1] == "export":
                        self._export_skin(parts[0])
                    else:
                        self.send_error(HTTPStatus.NOT_FOUND)
                else:
                    self.send_error(HTTPStatus.NOT_FOUND)

            def _handle_api_post(self, parsed: urllib.parse.ParseResult) -> None:
                try:
                    if parsed.path == "/api/service/start":
                        app.request_service_action("start")
                        self._json({"ok": True, "action": "start"})
                    elif parsed.path == "/api/service/stop":
                        app.request_service_action("stop")
                        self._json({"ok": True, "action": "stop"})
                    elif parsed.path == "/api/service/restart":
                        app.request_service_action("restart")
                        self._json({"ok": True, "action": "restart"})
                    elif parsed.path == "/api/modules/export":
                        body = self._body_json()
                        raw_modules = body.get("modules")
                        selected = (
                            [str(item).strip() for item in raw_modules if str(item).strip()]
                            if isinstance(raw_modules, list)
                            else None
                        )
                        exported = app.export_modules_config(selected)
                        self._json({"ok": True, "export": exported})
                    elif parsed.path == "/api/modules/import":
                        body = self._body_json(max_bytes=4 * 1024 * 1024)
                        if isinstance(body.get("data"), dict):
                            payload = body["data"]
                            raw_selected = body.get("modules")
                            selected = (
                                [str(item).strip() for item in raw_selected if str(item).strip()]
                                if isinstance(raw_selected, list)
                                else None
                            )
                            apply_enabled = bool(body.get("apply_enabled", True))
                        else:
                            payload = body
                            selected = None
                            apply_enabled = True
                        result = app.import_modules_config(
                            payload,
                            module_ids=selected,
                            apply_enabled=apply_enabled,
                        )
                        self._json({"ok": True, **result})
                    elif parsed.path == "/api/modules/magnet_import/channel-scan":
                        body = self._body_json()
                        started = app.request_magnet_channel_scan(
                            bool(body.get("full", True)), bool(body.get("rebuild", False))
                        )
                        if not started:
                            self._json({"ok": False, "error": "无法开始：模块或频道来源未启用、Telegram 未连接，或已有扫描在进行"}, HTTPStatus.CONFLICT)
                            return
                        module = app.modules.get("magnet_import")
                        self._json({"ok": True, "module": module.card.__dict__ if module else None})
                    elif parsed.path == "/api/modules/rex_widget_sync/scan":
                        body = self._body_json()
                        if not app.request_rex_widget_scan(bool(body.get("full", True))):
                            self._json({"ok": False, "error": "无法开始：模块未启用、Telegram 未连接，或已有同步在进行"}, HTTPStatus.CONFLICT)
                            return
                        module = app.modules.get("rex_widget_sync")
                        self._json({"ok": True, "module": module.card.__dict__ if module else None})
                    elif parsed.path == "/api/modules/magnet_import/avdb-run":
                        body = self._body_json()
                        started = app.request_magnet_avdb_run(
                            bool(body.get("force", True)),
                            bool(body.get("rebuild", False)),
                            bool(body.get("update_existing", False)),
                        )
                        if not started:
                            self._json({"ok": False, "error": "无法开始：模块未启用，或已有 AVDB 任务在运行"}, HTTPStatus.CONFLICT)
                            return
                        module = app.modules.get("magnet_import")
                        self._json({"ok": True, "module": module.card.__dict__ if module else None})
                    elif parsed.path == "/api/modules/magnet_import/channel-export":
                        result = app.run_magnet_channel_export()
                        module = app.modules.get("magnet_import")
                        status = HTTPStatus.OK if result.get("status") in {"sent", "empty"} else HTTPStatus.CONFLICT
                        self._json(
                            {"ok": status == HTTPStatus.OK, "result": result, "error": result.get("detail", ""),
                             "module": module.card.__dict__ if module else None},
                            status,
                        )
                    elif parsed.path == "/api/ui/wallpaper":
                        body = self._body_json(max_bytes=MAX_WALLPAPER_BODY_BYTES)
                        _prefs_path, wallpapers_dir = resolve_ui_paths(app)
                        saved = save_uploaded_wallpaper(
                            wallpapers_dir,
                            str(body.get("filename") or "wallpaper"),
                            str(body.get("data_url") or ""),
                        )
                        self._json({"ok": True, "wallpaper": saved, "wallpapers": saved["wallpapers"]})
                    elif parsed.path == "/api/ui/wallpaper/delete":
                        body = self._body_json()
                        _prefs_path, wallpapers_dir = resolve_ui_paths(app)
                        wallpapers = delete_uploaded_wallpaper(wallpapers_dir, str(body.get("name") or ""))
                        self._json({"ok": True, "wallpapers": wallpapers})
                    elif parsed.path == "/api/ui/skins/import":
                        body = self._body_json(max_bytes=MAX_SKIN_BODY_BYTES)
                        skins_dir = resolve_skins_dir(app)
                        imported = import_mvskin_base64(
                            skins_dir,
                            str(body.get("filename") or "skin.mvskin"),
                            str(body.get("data_b64") or ""),
                        )
                        self._json({"ok": True, **imported})
                    elif parsed.path == "/api/ui/skins/update":
                        body = self._body_json()
                        skins_dir = resolve_skins_dir(app)
                        updated = update_skin_meta(skins_dir, str(body.get("id") or ""), body)
                        self._json({"ok": True, **updated})
                    elif parsed.path == "/api/ui/skins/delete":
                        body = self._body_json()
                        skins_dir = resolve_skins_dir(app)
                        skins = delete_skin(skins_dir, str(body.get("id") or ""))
                        self._json({"ok": True, "skins": skins})
                    else:
                        self.send_error(HTTPStatus.NOT_FOUND)
                except ValueError as exc:
                    self._json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
                except Exception as exc:
                    logger.exception("POST %s failed", parsed.path)
                    self._json({"ok": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

            def _handle_api_put(self, parsed: urllib.parse.ParseResult) -> None:
                try:
                    body = self._body_json()
                except ValueError as exc:
                    self._json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
                    return
                if parsed.path == "/api/ai":
                    try:
                        self._json({"ok": True, "ai": app.update_ai_config(body)})
                    except ValueError as exc:
                        self._json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
                    except Exception as exc:
                        logger.exception("Failed to update AI config")
                        self._json({"ok": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                elif parsed.path == "/api/settings":
                    try:
                        app.update_settings(body)
                        self._json({"ok": True, "settings": app.settings_snapshot()})
                    except Exception as exc:
                        logger.exception("Failed to update settings")
                        self._json({"ok": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                elif parsed.path == "/api/ui/preferences":
                    try:
                        prefs_path, wallpapers_dir = resolve_ui_paths(app)
                        updated = save_ui_preferences(prefs_path, wallpapers_dir, body)
                        self._json({"ok": True, "preferences": updated})
                    except Exception as exc:
                        logger.exception("Failed to update UI preferences")
                        self._json({"ok": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                elif parsed.path.startswith("/api/modules/"):
                    module_id = parsed.path.rsplit("/", 1)[-1]
                    try:
                        updated = app.update_module(module_id, body)
                    except ValueError as exc:
                        self._json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
                        return
                    except Exception as exc:
                        logger.exception("Failed to update module: %s", module_id)
                        self._json({"ok": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
                        return
                    if updated is None:
                        self.send_error(HTTPStatus.NOT_FOUND)
                        return
                    self._json({"ok": True, "module": updated})
                else:
                    self.send_error(HTTPStatus.NOT_FOUND)

            def _serve_static(self, path: str, static_dir: Path) -> None:
                relative = "index.html" if path in {"", "/"} else path.lstrip("/")
                target = (static_dir / relative).resolve()
                if static_dir.resolve() not in target.parents and target != static_dir.resolve():
                    self.send_error(HTTPStatus.FORBIDDEN)
                    return
                if not target.exists() or not target.is_file():
                    target = static_dir / "index.html"
                stat = target.stat()
                etag = f'W/"{stat.st_mtime_ns:x}-{stat.st_size:x}"'
                if (self.headers.get("If-None-Match") or "").strip() == etag:
                    self.send_response(HTTPStatus.NOT_MODIFIED)
                    self.send_header("ETag", etag)
                    self.send_header("Cache-Control", "no-cache, must-revalidate")
                    self.end_headers()
                    return
                if target.suffix == ".webmanifest":
                    content_type = "application/manifest+json"
                else:
                    content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                data = target.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.send_header("ETag", etag)
                self.send_header("Cache-Control", "no-cache, must-revalidate")
                if target.suffix in {".html", ".css", ".js", ".webmanifest"}:
                    self.send_header("Pragma", "no-cache")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _download_log(self, name: str) -> None:
                log_dir = (app.project_root / app.config.logs.dir).resolve()
                target = (log_dir / name).resolve()
                if log_dir not in target.parents or not target.is_file():
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                data = target.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="{target.name}"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _serve_wallpaper(self, name: str) -> None:
                _prefs_path, wallpapers_dir = resolve_ui_paths(app)
                target = resolve_wallpaper_file(wallpapers_dir, name)
                if target is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                data = target.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "public, max-age=31536000, immutable")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(data)

            def _serve_skin_asset(self, skin_id: str, asset: str) -> None:
                skins_dir = resolve_skins_dir(app)
                target = resolve_skin_asset(skins_dir, skin_id, asset)
                if target is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                content_type = mimetypes.guess_type(target.name)[0] or "image/webp"
                data = target.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "public, max-age=3600")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(data)

            def _export_skin(self, skin_id: str) -> None:
                skins_dir = resolve_skins_dir(app)
                exported = export_mvskin_bytes(skins_dir, skin_id)
                if exported is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                filename, payload = exported
                encoded_name = urllib.parse.quote(filename, safe="")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/zip")
                self.send_header(
                    "Content-Disposition",
                    f"attachment; filename=\"skin.mvskin\"; filename*=UTF-8''{encoded_name}",
                )
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(payload)

            def _body_json(self, max_bytes: int = _MAX_BODY_BYTES) -> dict[str, Any]:
                raw_length = self.headers.get("Content-Length", "0")
                try:
                    length = int(raw_length)
                except ValueError as exc:
                    raise ValueError("invalid Content-Length header") from exc
                if length <= 0:
                    return {}
                if length > max_bytes:
                    raise ValueError(f"request body exceeds {max_bytes} bytes")
                try:
                    raw = self.rfile.read(length).decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise ValueError("request body must be UTF-8") from exc
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    return {}
                return data if isinstance(data, dict) else {}

            def _json(self, data: Any, status: HTTPStatus = HTTPStatus.OK, headers: dict[str, str] | None = None) -> None:
                payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(payload)

        return Handler


def _login_page(next_url: str) -> str:
    safe_next_js = json.dumps(_safe_next_url(next_url)).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="zh-CN" data-theme="dark">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Telebot 登录</title>
    <meta name="theme-color" content="#080a0f" />
    <script>
      (() => {{
        try {{
          const saved = localStorage.getItem("telegrambot.admin.theme.v1");
          const theme = saved === "light" || saved === "dark" ? saved : "dark";
          document.documentElement.dataset.theme = theme;
        }} catch (_e) {{}}
      }})();
    </script>
    <style>
      :root, [data-theme="dark"] {{
        color-scheme: dark;
        --bg: #110e0d;
        --bg-dot: rgba(246, 239, 238, 0.04);
        --bg-glow-a: rgba(192, 99, 89, 0.18);
        --bg-glow-b: rgba(172, 118, 102, 0.12);
        --surface: rgba(29, 23, 22, 0.78);
        --surface-solid: #1d1716;
        --surface-recessed: rgba(17, 14, 13, 0.72);
        --surface-input: rgba(17, 14, 13, 0.85);
        --surface-hover: rgba(246, 239, 238, 0.06);
        --border: rgba(236, 202, 198, 0.14);
        --border-strong: rgba(236, 202, 198, 0.22);
        --rim: rgba(255, 244, 242, 0.08);
        --ink: #f6efee;
        --ink-secondary: #decbc8;
        --muted: #b09491;
        --accent: #c06359;
        --accent-hover: #cf7268;
        --accent-soft: rgba(192, 99, 89, 0.16);
        --accent-border: rgba(192, 99, 89, 0.36);
        --accent-on: #fff9f8;
        --danger: #e4746a;
        --danger-soft: rgba(228, 116, 106, 0.14);
        --danger-border: rgba(228, 116, 106, 0.34);
        --shadow: 0 18px 46px -10px rgba(0, 0, 0, 0.68), 0 36px 76px -18px rgba(0, 0, 0, 0.8);
        --shadow-accent: 0 6px 18px -4px rgba(192, 99, 89, 0.36);
      }}
      [data-theme="light"] {{
        color-scheme: light;
        --bg: #f7f5f5;
        --bg-dot: rgba(41, 22, 20, 0.045);
        --bg-glow-a: rgba(172, 69, 57, 0.11);
        --bg-glow-b: rgba(174, 85, 56, 0.08);
        --surface: rgba(253, 252, 252, 0.88);
        --surface-solid: #fdfcfc;
        --surface-recessed: #ede9e8;
        --surface-input: #ffffff;
        --surface-hover: rgba(41, 22, 20, 0.05);
        --border: rgba(80, 47, 43, 0.12);
        --border-strong: rgba(80, 47, 43, 0.2);
        --rim: rgba(255, 255, 255, 0.92);
        --ink: #291614;
        --ink-secondary: #502f2b;
        --muted: #7c5450;
        --accent: #ac4539;
        --accent-hover: #963a2f;
        --accent-soft: rgba(172, 69, 57, 0.11);
        --accent-border: rgba(172, 69, 57, 0.3);
        --accent-on: #ffffff;
        --danger: #c83e4b;
        --danger-soft: rgba(200, 62, 75, 0.1);
        --danger-border: rgba(200, 62, 75, 0.28);
        --shadow: 0 10px 30px -10px rgba(41, 22, 20, 0.12), 0 30px 64px -20px rgba(41, 22, 20, 0.16);
        --shadow-accent: 0 6px 18px -4px rgba(172, 69, 57, 0.34);
      }}
      html {{
        font-size: 14px;
        -webkit-font-smoothing: antialiased;
      }}
      @media (min-width: 2200px) {{
        html {{ font-size: clamp(14.5px, 0.44vw + 4.8px, 16.5px); }}
      }}
      @media (min-width: 3100px) {{
        html {{ font-size: clamp(16.5px, 0.42vw + 2.2px, 19px); }}
      }}
      *, *::before, *::after {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        min-height: 100vh;
        display: grid;
        place-items: center;
        padding: 1.5rem 1rem;
        color: var(--ink);
        font-family: "PingFang SC", "HarmonyOS Sans SC", "Hiragino Sans GB", "Microsoft YaHei UI", "SF Pro Display", "Segoe UI", system-ui, sans-serif;
        background-color: var(--bg);
        background-image:
          radial-gradient(46rem 32rem at 18% 8%, var(--bg-glow-a), transparent 68%),
          radial-gradient(42rem 30rem at 85% 90%, var(--bg-glow-b), transparent 68%),
          radial-gradient(var(--bg-dot) 1px, transparent 1px);
        background-size: 100% 100%, 100% 100%, 24px 24px;
      }}
      .theme-fab {{
        position: fixed;
        top: 1.25rem;
        right: 1.25rem;
        width: 2.6rem;
        height: 2.6rem;
        padding: 0;
        display: inline-grid;
        place-items: center;
        border-radius: 0.72rem;
        border: 1px solid var(--border-strong);
        background: var(--surface);
        color: var(--ink-secondary);
        cursor: pointer;
        backdrop-filter: blur(16px);
        transition: border-color 150ms ease, color 150ms ease, transform 150ms ease;
      }}
      .theme-fab:hover {{
        border-color: var(--accent-border);
        color: var(--accent);
        transform: translateY(-1px);
      }}
      .theme-fab svg {{
        width: 1.15rem;
        height: 1.15rem;
        fill: none;
        stroke: currentColor;
        stroke-width: 1.8;
        stroke-linecap: round;
        stroke-linejoin: round;
      }}
      .login-panel {{
        position: relative;
        width: min(30rem, 100%);
        padding: 2.1rem 2rem 1.9rem;
        border: 1px solid var(--border);
        border-radius: 1.25rem;
        background: var(--surface);
        box-shadow: var(--shadow), inset 0 1px 0 var(--rim);
        backdrop-filter: blur(24px) saturate(160%);
        overflow: hidden;
        animation: cardIn 260ms cubic-bezier(0.22, 1, 0.36, 1);
      }}
      .login-panel::before {{
        content: "";
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 2px;
        background: linear-gradient(90deg, var(--accent), rgba(226, 164, 82, 0.55), transparent);
      }}
      @keyframes cardIn {{
        from {{ opacity: 0; transform: translateY(10px) scale(0.985); }}
        to {{ opacity: 1; transform: translateY(0) scale(1); }}
      }}
      .brand-head {{
        display: flex;
        align-items: center;
        gap: 0.9rem;
        margin-bottom: 1.25rem;
      }}
      .brand-badge {{
        width: 3.1rem;
        height: 3.1rem;
        border-radius: 0.85rem;
        overflow: hidden;
        flex: none;
        border: 1px solid var(--border-strong);
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.16);
      }}
      .brand-badge img {{ width: 100%; height: 100%; display: block; object-fit: cover; }}
      .brand-eyebrow {{
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
        font-family: ui-monospace, "JetBrains Mono", Consolas, monospace;
        font-size: 0.74rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--accent);
        margin-bottom: 0.18rem;
      }}
      .brand-eyebrow::before {{
        content: "";
        width: 0.45rem;
        height: 0.45rem;
        border-radius: 50%;
        background: var(--accent);
        box-shadow: 0 0 8px var(--accent);
      }}
      h1 {{
        margin: 0;
        font-size: 1.42rem;
        font-weight: 750;
        letter-spacing: -0.025em;
        line-height: 1.25;
      }}
      .subtitle {{
        margin: 0 0 1.5rem;
        padding: 0.72rem 0.88rem;
        border-radius: 0.65rem;
        background: var(--surface-recessed);
        border: 1px solid var(--border);
        font-size: 0.84rem;
        color: var(--muted);
        line-height: 1.55;
      }}
      form {{ display: grid; gap: 1.05rem; }}
      label {{
        display: grid;
        gap: 0.45rem;
        font-size: 0.86rem;
        font-weight: 650;
        color: var(--ink-secondary);
      }}
      .field-wrap {{
        position: relative;
        display: flex;
        align-items: center;
      }}
      input {{
        width: 100%;
        min-height: 2.8rem;
        border: 1px solid var(--border-strong);
        border-radius: 0.65rem;
        padding: 0.6rem 0.88rem;
        color: var(--ink);
        background: var(--surface-input);
        font: inherit;
        font-size: 0.95rem;
        transition: border-color 150ms ease, box-shadow 150ms ease, background-color 150ms ease;
      }}
      .field-wrap input {{ padding-right: 4.4rem; }}
      input:focus {{
        outline: none;
        border-color: var(--accent);
        box-shadow: 0 0 0 3px var(--accent-soft);
        background: var(--surface-solid);
      }}
      .pw-toggle {{
        position: absolute;
        right: 0.4rem;
        height: 2rem;
        padding: 0 0.65rem;
        border: 1px solid transparent;
        border-radius: 0.45rem;
        background: transparent;
        color: var(--muted);
        font: inherit;
        font-size: 0.8rem;
        font-weight: 600;
        cursor: pointer;
      }}
      .pw-toggle:hover {{
        color: var(--ink);
        background: var(--surface-hover);
      }}
      .submit-btn {{
        margin-top: 0.35rem;
        min-height: 2.95rem;
        border: 0;
        border-radius: 0.72rem;
        color: var(--accent-on);
        background: var(--accent);
        box-shadow: var(--shadow-accent), inset 0 1px 0 rgba(255, 255, 255, 0.25);
        cursor: pointer;
        font: inherit;
        font-size: 0.96rem;
        font-weight: 700;
        letter-spacing: 0.01em;
        transition: background-color 150ms ease, transform 140ms ease, opacity 150ms ease;
      }}
      .submit-btn:hover:not(:disabled) {{
        background: var(--accent-hover);
        transform: translateY(-1px);
      }}
      .submit-btn:active:not(:disabled) {{ transform: translateY(0); }}
      .submit-btn:disabled {{ opacity: 0.6; cursor: not-allowed; }}
      .error {{
        min-height: 1.25rem;
        font-size: 0.86rem;
        font-weight: 600;
        color: var(--danger);
        border-radius: 0.6rem;
      }}
      .error:not(:empty) {{
        padding: 0.68rem 0.85rem;
        background: var(--danger-soft);
        border: 1px solid var(--danger-border);
      }}
    </style>
  </head>
  <body>
    <button id="loginThemeToggle" class="theme-fab" type="button" aria-label="切换深色/浅色主题" title="切换深色/浅色主题"></button>
    <main class="login-panel">
      <div class="brand-head">
        <span class="brand-badge" aria-hidden="true">
          <img src="/assets/telegrambot-logo.png?v=20261124" alt="Telebot" />
        </span>
        <div>
          <span class="brand-eyebrow">Console</span>
          <h1>Telebot 登录</h1>
        </div>
      </div>
      <p class="subtitle">登录状态保存在当前服务进程内；服务重启后需要重新登录。</p>
      <form id="loginForm">
        <label>
          <span>用户名</span>
          <input name="username" autocomplete="username" placeholder="请输入管理员用户名" required autofocus />
        </label>
        <label>
          <span>密码</span>
          <span class="field-wrap">
            <input id="passwordInput" name="password" type="password" autocomplete="current-password" placeholder="请输入访问密码" required />
            <button id="togglePw" class="pw-toggle" type="button" aria-pressed="false">显示</button>
          </span>
        </label>
        <button class="submit-btn" type="submit">登录控制台</button>
        <div id="loginError" class="error" role="alert"></div>
      </form>
    </main>
    <script>
      const nextUrl = {safe_next_js};
      const THEME_KEY = "telegrambot.admin.theme.v1";
      const sunSvg = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2.5 12h2M19.5 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
      const moonSvg = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20.2 14.8A8.5 8.5 0 0 1 9.2 3.8a8.5 8.5 0 1 0 11 11z"/></svg>';
      const themeBtn = document.getElementById("loginThemeToggle");
      function syncThemeBtn() {{
        const dark = document.documentElement.dataset.theme !== "light";
        themeBtn.innerHTML = dark ? sunSvg : moonSvg;
        themeBtn.setAttribute("aria-label", dark ? "切换到浅色主题" : "切换到深色主题");
      }}
      syncThemeBtn();
      themeBtn.addEventListener("click", () => {{
        const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
        document.documentElement.dataset.theme = next;
        try {{ localStorage.setItem(THEME_KEY, next); }} catch (_e) {{}}
        syncThemeBtn();
      }});
      const pwInput = document.getElementById("passwordInput");
      const togglePw = document.getElementById("togglePw");
      togglePw.addEventListener("click", () => {{
        const shown = pwInput.type === "text";
        pwInput.type = shown ? "password" : "text";
        togglePw.textContent = shown ? "显示" : "隐藏";
        togglePw.setAttribute("aria-pressed", String(!shown));
      }});
      document.getElementById("loginForm").addEventListener("submit", async (event) => {{
        event.preventDefault();
        const form = event.currentTarget;
        const error = document.getElementById("loginError");
        error.textContent = "";
        const button = form.querySelector(".submit-btn");
        button.disabled = true;
        button.textContent = "正在验证...";
        try {{
          const response = await fetch("/api/login", {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify({{
              username: form.elements.username.value,
              password: form.elements.password.value,
            }}),
          }});
          if (!response.ok) throw new Error("用户名或密码不正确");
          window.location.assign(nextUrl || "/");
        }} catch (err) {{
          error.textContent = err.message || "登录失败";
          button.textContent = "登录控制台";
        }} finally {{
          button.disabled = false;
        }}
      }});
    </script>
  </body>
</html>"""
