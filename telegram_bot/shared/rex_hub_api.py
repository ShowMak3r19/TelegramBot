"""Rex Widget Hub（nfhgw295/rex-widgets-hub）管理接口适配层。

接口来自其管理页源码（/app/worker.js、uploads.js）：
- POST /api/admin/auth {password}            → Cookie fwh_admin
- GET  /api/admin/modules                     → 模块列表
- POST /api/admin/modules  (multipart files)  → 单文件新增；按模块 ID / 完整文件名命中时直接替换
- PUT  /api/admin/modules?id=  (multipart file, mode) → 替换指定模块（保留合集/分组/链接）
- PATCH /api/admin/modules?id= {title,title_locked,version}
- GET  /api/admin/collections                 → 合集（含 moduleIds）
- POST /api/admin/modules/bulk {action:"append",ids,collectionId} → 追加进合集

加密模块（首行 REXENC）Hub 读不到 WidgetMetadata，只能按完整文件名匹配，
所以模块身份由调用方自己维护，替换时用 PUT 显式指定目标。
同步调用，请在 asyncio.to_thread 中使用。
"""

from __future__ import annotations

from typing import Any

from telegram_bot.shared.net import ensure_http_url


class RexHubError(RuntimeError):
    pass


class RexHubClient:
    def __init__(self, base_url: str, password: str, *, timeout: float = 120.0) -> None:
        import httpx  # openai SDK 的依赖，运行环境已安装

        self.base = ensure_http_url(base_url).rstrip("/")
        self._client = httpx.Client(timeout=httpx.Timeout(timeout, connect=15.0), follow_redirects=False)
        self._password = password
        self._authed = False

    def __enter__(self) -> "RexHubClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def login(self) -> None:
        if not self._password:
            raise RexHubError("未配置 Hub 管理密码")
        data = self._request("POST", "/api/admin/auth", json={"password": self._password}, auth=False)
        if not data.get("ok"):
            raise RexHubError("Hub 登录失败：密码错误")
        self._authed = True

    def list_modules(self) -> list[dict[str, Any]]:
        data = self._request("GET", "/api/admin/modules")
        if not isinstance(data, list):
            raise RexHubError("Hub 模块列表格式异常")
        return data

    def list_collections(self) -> list[dict[str, Any]]:
        data = self._request("GET", "/api/admin/collections")
        if not isinstance(data, list):
            raise RexHubError("Hub 合集列表格式异常")
        return data

    def find_collection(self, slug: str) -> dict[str, Any]:
        for item in self.list_collections():
            if str(item.get("slug") or "") == slug or str(item.get("title") or "") == slug:
                return item
        raise RexHubError(f"Hub 中没有合集 {slug}")

    def upload_new(self, filename: str, content: bytes, *, group_id: str = "") -> dict[str, Any]:
        """返回 {status: added|replaced|unchanged, module_id}。"""
        data = self._request(
            "POST",
            "/api/admin/modules",
            files={"files": (filename, content, "text/javascript")},
            data={"group_id": group_id} if group_id else {},
        )
        return _result(data)

    def replace(self, module_id: str, filename: str, content: bytes, *, mode: str = "") -> dict[str, Any]:
        data = self._request(
            "PUT",
            "/api/admin/modules",
            params={"id": module_id},
            files={"file": (filename, content, "text/javascript")},
            data={"mode": mode} if mode else {},
        )
        return _result(data)

    def update_meta(self, module_id: str, *, title: str = "", version: str = "", lock_title: bool = True) -> None:
        body: dict[str, Any] = {}
        if title:
            body["title"] = title
            body["title_locked"] = bool(lock_title)
        if version:
            body["version"] = version
        if body:
            self._request("PATCH", "/api/admin/modules", params={"id": module_id}, json=body)

    def delete_module(self, module_id: str) -> None:
        data = self._request("DELETE", "/api/admin/modules", params={"id": module_id})
        if not data.get("ok"):
            raise RexHubError(f"Hub 删除模块失败：{data}")

    def append_to_collection(self, collection_id: str, module_id: str) -> None:
        data = self._request(
            "POST",
            "/api/admin/modules/bulk",
            json={"action": "append", "ids": [module_id], "collectionId": collection_id},
        )
        failed = [r for r in data.get("results", []) if isinstance(r, dict) and not r.get("ok")]
        if failed:
            raise RexHubError(f"加入合集失败：{failed[0].get('error') or '未知错误'}")

    def _request(self, method: str, path: str, *, auth: bool = True, **kwargs: Any) -> Any:
        if auth and not self._authed:
            self.login()
        response = self._client.request(method, f"{self.base}{path}", **kwargs)
        try:
            data = response.json()
        except ValueError:
            data = None
        if response.status_code == 401:
            raise RexHubError("Hub 未授权（密码错误或会话失效）")
        if response.status_code >= 400:
            error = data.get("error") if isinstance(data, dict) else ""
            raise RexHubError(f"Hub {method} {path} 失败 HTTP {response.status_code}：{error or response.text[:200]}")
        if data is None:
            raise RexHubError(f"Hub {method} {path} 返回非 JSON")
        return data


def _result(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict) or not data.get("ok") or not data.get("module_id"):
        error = data.get("error") if isinstance(data, dict) else ""
        raise RexHubError(f"Hub 上传失败：{error or data}")
    return data
