"""AVDB 资源库 GitHub release 适配层：查询最新版本、下载资源包、调用转换脚本得到 CSV。

资源包是 AES-256-GCM 加密的 ZIP，由用户提供的 scripts/avdb/resource_to_csv.sh 解密并转成 MagnetBoard
可导入的 CSV（脚本原样保留，这里只按它的 SH 启动方式执行内嵌 Python）。
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from telegram_bot.shared.net import ensure_http_url

_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_MAX_ASSET_BYTES = 2 * 1024 * 1024 * 1024
_SAFE_SUBPROCESS_ENV_KEYS = (
    "PATH",
    "HOME",
    "USERPROFILE",
    "TEMP",
    "TMP",
    "TMPDIR",
    "SYSTEMROOT",
    "LOCALAPPDATA",
    "APPDATA",
    "XDG_CACHE_HOME",
    "LANG",
    "LC_ALL",
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
)

# 与脚本 SH 启动器里的 python -c 一致：取出内嵌 Python 段执行
_LAUNCHER = (
    "import os,pathlib; p=pathlib.Path(os.environ['RESOURCE_CSV_LAUNCHER_PATH']); "
    "s=p.read_text(encoding='utf-8-sig').split(chr(10)+'# __RESOURCE_CSV_PYTHON__'+chr(10),1)[1]"
    ".split(chr(10)+'# __RESOURCE_CSV_END__',1)[0]; "
    "exec(compile(s,str(p),'exec'),{'__name__':'__main__','__file__':str(p)})"
)


class AvdbReleaseError(RuntimeError):
    pass


@dataclass
class ReleaseAsset:
    tag: str
    name: str
    url: str
    size: int
    sha256: str  # release 说明里给出的 SHA-256，没有则为空


def latest_asset_sync(repo: str, pattern: str, *, timeout: float = 30.0) -> ReleaseAsset:
    """查询仓库最新 release，返回第一个文件名匹配 pattern 的附件。"""
    import httpx

    cleaned_repo = str(repo or "").strip().strip("/")
    if not _REPO_RE.fullmatch(cleaned_repo):
        raise AvdbReleaseError(f"非法的 GitHub 仓库名：{repo!r}")
    response = httpx.get(
        f"https://api.github.com/repos/{cleaned_repo}/releases/latest",
        headers={"Accept": "application/vnd.github+json"},
        timeout=timeout,
        follow_redirects=True,
    )
    if response.status_code >= 400:
        raise AvdbReleaseError(f"GitHub 查询 release 失败（{response.status_code}）")
    release = response.json()
    regex = re.compile(pattern, re.IGNORECASE)
    for asset in release.get("assets") or []:
        name = str(asset.get("name") or "")
        if regex.search(name):
            return ReleaseAsset(
                tag=str(release.get("tag_name") or ""),
                name=name,
                url=str(asset.get("browser_download_url") or ""),
                size=int(asset.get("size") or 0),
                sha256=_body_sha256(str(release.get("body") or ""), name),
            )
    raise AvdbReleaseError(f"最新 release {release.get('tag_name')} 中没有匹配 {pattern} 的资源包")


def download_asset_sync(asset: ReleaseAsset, dest: Path, *, timeout: float = 600.0) -> Path:
    """下载附件并校验大小与 SHA-256（release 说明里有时）。"""
    import httpx

    url = ensure_http_url(asset.url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    written = 0
    try:
        with httpx.stream("GET", url, timeout=httpx.Timeout(timeout, connect=15.0), follow_redirects=True) as response:
            if response.status_code >= 400:
                raise AvdbReleaseError(f"下载资源包失败（{response.status_code}）")
            with dest.open("wb") as fh:
                for chunk in response.iter_bytes(1024 * 1024):
                    written += len(chunk)
                    if written > _MAX_ASSET_BYTES:
                        raise AvdbReleaseError("资源包超过最大下载体积限制")
                    fh.write(chunk)
                    digest.update(chunk)
        if asset.size and dest.stat().st_size != asset.size:
            raise AvdbReleaseError(f"资源包大小不符：{dest.stat().st_size} != {asset.size}")
        if asset.sha256 and digest.hexdigest() != asset.sha256:
            raise AvdbReleaseError("资源包 SHA-256 与 release 说明不一致")
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return dest


def convert_zip_sync(
    script: Path,
    zip_path: Path,
    *,
    timeout: float = 600.0,
    allowed_root: Path | None = None,
) -> Path:
    """用转换脚本把资源包转成 CSV，返回 CSV 路径（脚本写在 ZIP 同目录）。"""
    script, zip_path = Path(script).resolve(), Path(zip_path).resolve()
    if allowed_root is not None:
        root = Path(allowed_root).resolve()
        if root not in script.parents and script != root:
            raise AvdbReleaseError(f"转换脚本路径越界：{script}")
    if not script.is_file():
        raise AvdbReleaseError(f"转换脚本不存在：{script}")
    env = {
        key: os.environ[key]
        for key in _SAFE_SUBPROCESS_ENV_KEYS
        if key in os.environ
    }
    env.update(
        {
            "RESOURCE_CSV_LAUNCHER_PATH": str(script),
            "RESOURCE_CSV_LAUNCHER_MODE": "sh",
            "RESOURCE_CSV_ALLOW_PIP": "0",
            "PYTHONUTF8": "1",
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", _LAUNCHER, str(zip_path)],
        cwd=str(zip_path.parent),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    output = (result.stdout or "") + (result.stderr or "")
    match = re.search(r"^CSV：(.+)$", output, re.MULTILINE)
    if result.returncode != 0 or not match:
        failure = re.search(r"^失败：(.+)$", output, re.MULTILINE)
        raise AvdbReleaseError(f"转换失败：{failure.group(1) if failure else output.strip()[-300:]}")
    return Path(match.group(1).strip())


def _body_sha256(body: str, name: str) -> str:
    match = re.search(re.escape(name) + r"`?\s*:\s*`?([0-9a-fA-F]{64})", body)
    return match.group(1).lower() if match else ""


def asset_summary(asset: ReleaseAsset) -> dict[str, Any]:
    return {"tag": asset.tag, "name": asset.name, "size": asset.size, "verified": bool(asset.sha256)}
