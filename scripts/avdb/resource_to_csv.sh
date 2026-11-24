#!/usr/bin/env bash
set -euo pipefail
script_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export RESOURCE_CSV_LAUNCHER_PATH="$script_dir/$(basename -- "${BASH_SOURCE[0]}")"
export RESOURCE_CSV_LAUNCHER_MODE=sh
export PYTHONUTF8=1
if command -v python3 >/dev/null 2>&1; then
    python_cmd=python3
elif command -v python >/dev/null 2>&1; then
    python_cmd=python
else
    printf '%s\n' '未找到 Python 3，请先安装 Python 3.9 或更新版本。' >&2
    exit 1
fi
if ! "$python_cmd" -c 'import sys; sys.exit(sys.version_info < (3,9))'; then
    printf '%s\n' '需要 Python 3.9 或更新版本。' >&2
    exit 1
fi
printf '%s\n' '资源库转 CSV'
exec "$python_cmd" -c "import os,pathlib; p=pathlib.Path(os.environ['RESOURCE_CSV_LAUNCHER_PATH']); s=p.read_text(encoding='utf-8-sig').split(chr(10)+'# __RESOURCE_CSV_PYTHON__'+chr(10),1)[1].split(chr(10)+'# __RESOURCE_CSV_END__',1)[0]; exec(compile(s,str(p),'exec'),{'__name__':'__main__','__file__':str(p)})" "$@"

: <<'__RESOURCE_CSV_EMBEDDED_PYTHON__'

# __RESOURCE_CSV_PYTHON__
#!/usr/bin/env python3
"""Encrypted resource ZIP -> import-ready CSV, with standalone BAT/SH launchers."""
from __future__ import annotations

import argparse
import base64
from collections import Counter
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
import errno
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import parse_qs, urlsplit, urlunsplit
import zipfile

FIELDS = (
    'id', 'title', 'content', 'url', 'images', 'magnets', 'code', 'size',
    'is_uncensored', 'author', 'forum_id', 'forum_type', 'magnet_hash',
    'published_at', 'created_at', 'source_site', 'duration', 'resolution',
    'format', 'language', 'subtitles', 'cover_url', 'local_cover_path',
    'screenshot_urls', 'local_screenshot_paths', 'poster_urls', 'tags',
    'categories', 'download_count', 'view_count', 'rating', 'in_emby',
    'emby_item_id', 'emby_checked_at', 'image_download_status',
    'image_retry_count', 'image_last_attempt_at', 'image_error_message',
    'is_downloaded', 'forum_name', 'import_identity',
)
LIMITS = {
    'title': 500, 'url': 500, 'code': 100, 'size': 50, 'forum_id': 128,
    'forum_type': 200, 'forum_name': 200, 'magnet_hash': 64, 'source_site': 50,
    'cover_url': 500,
}
MANIFEST = 'avdb-resource-library.json'
MAX_MANIFEST_BYTES = 64 * 1024
MAX_PBKDF2_ITERATIONS = 1_000_000
MAX_DECOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
# Fixed package key material shipped with AVDB's resource ZIP format v1.
PACKAGE_KEY = bytes.fromhex('ca42e687df5818e2e88da0ff5b9fd2c60f7e22721f682b66c3e50485a00d06d5')


class ConversionError(ValueError):
    pass


def load_crypto():
    """Use existing dependencies first; otherwise install into a private cache."""
    cache_root = os.environ.get('LOCALAPPDATA') if os.name == 'nt' else os.environ.get('XDG_CACHE_HOME')
    cache = Path(cache_root or Path.home() / '.cache') / 'resource-csv-converter' / (
        'python%d.%d-%s' % (sys.version_info.major, sys.version_info.minor, sys.platform)
    )
    if cache.is_dir() and str(cache) not in sys.path:
        sys.path.append(str(cache))
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        return Cipher, algorithms, modes
    except ImportError:
        pass
    if os.environ.get('RESOURCE_CSV_ALLOW_PIP', '1') == '0':
        raise ConversionError('缺少 cryptography 依赖，请通过 requirements.txt 或 conda 环境预先安装。')
    print('首次运行：正在安装解密依赖，需要联网……', flush=True)
    cache.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([
        sys.executable, '-m', 'pip', 'install', '--disable-pip-version-check',
        '--no-warn-script-location', '--only-binary=:all:', '--target', str(cache), 'cryptography',
    ], check=False)
    if result.returncode:
        raise ConversionError('解密依赖安装失败；请确认 Python 已安装 pip，并检查网络后重试。')
    if str(cache) not in sys.path:
        sys.path.append(str(cache))
    importlib.invalidate_caches()
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        return Cipher, algorithms, modes
    except ImportError as exc:
        raise ConversionError('无法加载解密依赖，请检查当前 Python 环境。') from exc


def decrypt_archive(source, temporary_directory):
    """Authenticate the package before reading its plaintext ZIP."""
    try:
        archive = zipfile.ZipFile(source)
    except zipfile.BadZipFile as exc:
        raise ConversionError('不是有效 ZIP；请使用完整资源库导出 ZIP。') from exc
    with archive:
        names = archive.namelist()
        if MANIFEST not in names:
            if any(name.lower().endswith('.bin') for name in names):
                raise ConversionError('缺少配套解密清单，请提供完整导出 ZIP。')
            return source
        if names.count(MANIFEST) != 1:
            raise ConversionError('压缩包包含重复的加密清单。')
        try:
            manifest_info = archive.getinfo(MANIFEST)
            if manifest_info.file_size > MAX_MANIFEST_BYTES:
                raise ConversionError('资源库加密清单体积过大。')
            manifest = json.loads(archive.read(MANIFEST).decode('utf-8-sig'))
            if not isinstance(manifest, dict):
                raise ValueError('manifest')
            if (manifest.get('format') != 'avdb-resource-library'
                    or manifest.get('version') != 1
                    or manifest.get('algorithm') != 'AES-256-GCM'
                    or manifest.get('kdf') != 'PBKDF2-HMAC-SHA256'):
                raise ConversionError('此脚本不支持该资源包的导出格式或版本。')
            salt, nonce, tag = (
                base64.b64decode(manifest[key], validate=True) for key in ('salt', 'nonce', 'tag')
            )
            iterations = int(manifest.get('iterations') or 200_000)
            payload = manifest['payload']
            if (len(salt) != 16 or len(nonce) != 12 or len(tag) != 16
                    or not 1 <= iterations <= MAX_PBKDF2_ITERATIONS or names.count(payload) != 1):
                raise ValueError('parameters')
            if archive.getinfo(payload).file_size > MAX_DECOMPRESSED_BYTES:
                raise ConversionError('资源包解压体积超过安全上限。')
        except ConversionError:
            raise
        except (KeyError, ValueError, TypeError, UnicodeError) as exc:
            raise ConversionError('资源库加密清单无效或缺少数据。') from exc
        Cipher, algorithms, modes = load_crypto()
        key = hashlib.pbkdf2_hmac('sha256', PACKAGE_KEY, salt, iterations, dklen=32)
        decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
        plaintext = Path(temporary_directory) / 'decoded.zip'
        from cryptography.exceptions import InvalidTag
        written = 0
        try:
            with archive.open(payload) as encrypted, plaintext.open('wb') as output:
                while True:
                    chunk = encrypted.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_DECOMPRESSED_BYTES:
                        raise ConversionError('资源包解压体积超过安全上限。')
                    output.write(decryptor.update(chunk))
                output.write(decryptor.finalize())
        except InvalidTag as exc:
            raise ConversionError('解密校验失败，压缩包可能损坏；请重新获取完整导出 ZIP。') from exc
        if not zipfile.is_zipfile(plaintext):
            raise ConversionError('解密结果不是有效的资源库 ZIP。')
        return plaintext


def array_value(value, *, strings_only=True):
    value = str(value or '').strip()
    if not value:
        return []
    if value.startswith('['):
        try:
            values = json.loads(value)
        except ValueError as exc:
            raise ConversionError('数组字段不是有效 JSON。') from exc
    else:
        values = [line.strip() for line in value.splitlines() if line.strip()]
    allowed = (str,) if strings_only else (str, dict)
    if not isinstance(values, list) or any(not isinstance(item, allowed) for item in values):
        raise ConversionError('数组字段的元素类型无效。')
    return values


def link_protocol(link):
    if link.lower().startswith('magnet:?'):
        topics = parse_qs(urlsplit(link).query).get('xt', [])
        if any(re.fullmatch(r'urn:btih:(?:[0-9a-f]{40}|[a-z2-7]{32})|urn:btmh:1220[0-9a-f]{64}',
                            topic, re.I) for topic in topics):
            return 'magnet'
    if re.fullmatch(r'ed2k://\|file\|[^|\r\n]+\|\d+\|[0-9a-f]{32}\|(?:[^|\r\n]*\|)*/', link, re.I):
        return 'ed2k'
    raise ConversionError('下载链接不是受支持的 magnet 或 ED2K 链接。')


def online_image_url(value):
    """Use the equivalent public image URL without downloading local assets."""
    value = str(value or '').strip()
    if not value:
        return ''
    try:
        parsed = urlsplit(value)
        if (parsed.scheme in ('http', 'https')
                and (parsed.hostname or '').lower() in (
                    'tp.spfcas.com', 'tp.cmastd.com', 'tp-iu.cmastd.com')
                and parsed.path.startswith('/rhe951l4q/')):
            return urlunsplit(('https', 'c0.jdbstatic.com',
                               parsed.path[len('/rhe951l4q'):], parsed.query, parsed.fragment))
    except ValueError:
        pass
    return value


def map_row(row):
    links = array_value(row.get('magnet') or row.get('magnets'))
    images = [online_image_url(url) for url in array_value(row.get('preview_images') or row.get('images'))]
    screenshots = [online_image_url(url) for url in array_value(row.get('screenshot_urls'))]
    posters = [online_image_url(url) for url in array_value(row.get('poster_urls'))]
    tags = array_value(row.get('resource_tags') or row.get('tags'), strings_only=False)
    categories = array_value(row.get('category') or row.get('categories'), strings_only=False)
    section = row.get('section') or row.get('forum_name') or row.get('forum_id') or ''
    size = row.get('size') or ''
    if row.get('size_bytes'):
        try:
            size_bytes = Decimal(row['size_bytes'])
            if not size_bytes.is_finite() or size_bytes < 0:
                raise InvalidOperation
            size = format(size_bytes / (1024 ** 3), '.2f') + ' GB'
        except InvalidOperation as exc:
            raise ConversionError('size_bytes 不是有效文件大小。') from exc
    elif size and re.fullmatch(r'\d+(?:\.\d+)?', size):
        size += ' MB'
    origin_id = row.get('tid') or row.get('magnet_hash') or hashlib.sha256(
        json.dumps(sorted(links), ensure_ascii=False).encode('utf-8')
    ).hexdigest()
    uncensored = row.get('is_uncensored', '').lower()
    if uncensored not in ('', 't', 'f', 'true', 'false', '1', '0', 'yes', 'no'):
        raise ConversionError('is_uncensored 不是有效布尔值。')
    uncensored = ('true' if uncensored in ('t', 'true', '1', 'yes') else
                  'false' if uncensored else
                  'true' if '破解' in section or '无码' in section else '')
    # Preserve the complete table layout; missing metadata and local state stay blank.
    record = dict.fromkeys(FIELDS, '')
    record.update(
        title=row.get('title') or '',
        # A movie detail URL may belong to several different resources.
        # Use the source and original ID to identify each resource instead.
        url='', images=json.dumps(images, ensure_ascii=False, separators=(',', ':')) if images else '',
        magnets=json.dumps(links, ensure_ascii=False, separators=(',', ':')),
        code=row.get('number') or row.get('code') or '', size=size,
        is_uncensored=uncensored, forum_id=section, forum_type=section, forum_name=section,
        magnet_hash=origin_id, published_at=row.get('publish_date') or row.get('published_at') or '',
        created_at=row.get('create_time') or row.get('created_at') or '',
        source_site=(row.get('website') or row.get('source_site') or 'custom').strip().lower(),
        cover_url=online_image_url(row.get('cover_url')) or (images[0] if images else ''),
        screenshot_urls=json.dumps(screenshots, ensure_ascii=False, separators=(',', ':')) if screenshots else '',
        poster_urls=json.dumps(posters, ensure_ascii=False, separators=(',', ':')) if posters else '',
        tags=json.dumps(tags, ensure_ascii=False, separators=(',', ':')) if tags else '',
        categories=json.dumps(categories, ensure_ascii=False, separators=(',', ':')) if categories else '',
    )
    if not record['title'].strip():
        raise ConversionError('标题不能为空。')
    if not links:
        raise ConversionError('资源缺少下载链接。')
    for link in links:
        link_protocol(link)
    for key, value in record.items():
        if '\x00' in value:
            raise ConversionError(key + ' 含有无效字符。')
        if key in LIMITS and len(value.strip()) > LIMITS[key]:
            raise ConversionError('%s 超过 %d 字符限制。' % (key, LIMITS[key]))
    for key in ('published_at', 'created_at'):
        if record[key]:
            try:
                datetime.fromisoformat(record[key].replace('Z', '+00:00'))
            except ValueError as exc:
                raise ConversionError(key + ' 不是有效 ISO 日期。') from exc
    return record


def publish_csv(temporary_path, source):
    """Publish without overwriting any existing CSV, including on repeated runs."""
    number = 1
    while True:
        suffix = '' if number == 1 else '_' + str(number)
        destination = source.with_name(source.stem + suffix + '.csv')
        try:
            os.link(temporary_path, destination)
        except FileExistsError:
            number += 1
            continue
        except OSError as exc:
            if exc.errno not in (errno.EPERM, errno.EXDEV, errno.EOPNOTSUPP, errno.ENOSYS, errno.EACCES, errno.EINVAL):
                raise
            # FAT/network shares may not support hard links. Exclusive creation
            # still protects existing output files on these filesystems.
            try:
                target = destination.open('xb')
            except FileExistsError:
                number += 1
                continue
            try:
                with target, temporary_path.open('rb') as stream:
                    shutil.copyfileobj(stream, target)
            except BaseException:
                target.close()
                destination.unlink(missing_ok=True)
                raise
        return destination


def convert_zip(source):
    source = Path(source).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != '.zip':
        raise ConversionError('请选择存在的完整 ZIP 文件：' + str(source))
    temporary_csv = None
    try:
        with tempfile.TemporaryDirectory(prefix='resource-csv-') as workspace:
            plain_zip = decrypt_archive(source, workspace)
            count, protocols, identities = 0, Counter(), set()
            with zipfile.ZipFile(plain_zip) as archive:
                members = sorted((item for item in archive.infolist()
                                  if not item.is_dir() and item.filename.lower().endswith('.csv')),
                                 key=lambda item: item.filename)
                if not members:
                    raise ConversionError('压缩包内没有 CSV；请使用资源库 CSV 导出包。')
                if sum(item.file_size for item in members) > MAX_DECOMPRESSED_BYTES:
                    raise ConversionError('压缩包内 CSV 解压体积超过安全上限。')
                descriptor, name = tempfile.mkstemp(prefix='.resource-csv-', suffix='.tmp', dir=source.parent)
                temporary_csv = Path(name)
                with os.fdopen(descriptor, 'w', encoding='utf-8', newline='') as output:
                    writer = csv.DictWriter(output, fieldnames=FIELDS)
                    writer.writeheader()
                    for member in members:
                        with archive.open(member) as raw, io.TextIOWrapper(raw, encoding='utf-8-sig', newline='') as stream:
                            reader = csv.DictReader(stream, strict=True)
                            headers = [str(key).strip().lower() for key in reader.fieldnames or []]
                            if (len(headers) != len(set(headers)) or 'title' not in headers
                                    or not {'magnet', 'magnets'}.intersection(headers)):
                                raise ConversionError(member.filename + ' 缺少标题/下载链接表头，或表头重复。')
                            reader.fieldnames = headers
                            for line_number, row in enumerate(reader, 2):
                                try:
                                    if None in row:
                                        raise ConversionError('列数超过表头，请检查 CSV 引号。')
                                    record = map_row({key: str(value or '') for key, value in row.items()})
                                    identity = (record['source_site'], record['magnet_hash'].strip())
                                    if identity in identities:
                                        raise ConversionError('同一来源存在重复资源编号，无法保证独立导入。')
                                    identities.add(identity)
                                    writer.writerow(record)
                                    protocols.update(link_protocol(link) for link in json.loads(record['magnets']))
                                    count += 1
                                except (ConversionError, ValueError) as exc:
                                    raise ConversionError('%s 第 %d 条记录：%s' % (member.filename, line_number, exc)) from exc
                if not count:
                    raise ConversionError('资源库没有可转换的记录。')
            destination = publish_csv(temporary_csv, source)
            return destination, count, protocols
    finally:
        if temporary_csv is not None:
            temporary_csv.unlink(missing_ok=True)


PICKER_SOURCE_BASE64 = 'dXNpbmcgU3lzdGVtOwp1c2luZyBTeXN0ZW0uQ29sbGVjdGlvbnMuR2VuZXJpYzsKdXNpbmcgU3lzdGVtLkRyYXdpbmc7CnVzaW5nIFN5c3RlbS5JTzsKdXNpbmcgU3lzdGVtLlRleHQ7CnVzaW5nIFN5c3RlbS5XZWIuU2NyaXB0LlNlcmlhbGl6YXRpb247CnVzaW5nIFN5c3RlbS5XaW5kb3dzLkZvcm1zOwoKc2VhbGVkIGNsYXNzIFJlc291cmNlQ3N2UGlja2VyIDogRm9ybQp7CiAgICBwdWJsaWMgc3RyaW5nW10gU2VsZWN0ZWRQYXRocyA9IG5ldyBzdHJpbmdbMF07CgogICAgcHVibGljIFJlc291cmNlQ3N2UGlja2VyKHN0cmluZyBpbml0aWFsRGlyZWN0b3J5KQogICAgewogICAgICAgIFRleHQgPSAi6LWE5rqQ5bqT6L2sIENTViI7CiAgICAgICAgQ2xpZW50U2l6ZSA9IG5ldyBTaXplKDU0MCwgMjgwKTsKICAgICAgICBTdGFydFBvc2l0aW9uID0gRm9ybVN0YXJ0UG9zaXRpb24uQ2VudGVyU2NyZWVuOwogICAgICAgIEZvcm1Cb3JkZXJTdHlsZSA9IEZvcm1Cb3JkZXJTdHlsZS5GaXhlZERpYWxvZzsKICAgICAgICBNYXhpbWl6ZUJveCA9IGZhbHNlOwogICAgICAgIEF1dG9TY2FsZU1vZGUgPSBBdXRvU2NhbGVNb2RlLk5vbmU7CiAgICAgICAgRm9udCA9IG5ldyBGb250KCJNaWNyb3NvZnQgWWFIZWkgVUkiLCAxMSk7CiAgICAgICAgQmFja0NvbG9yID0gQ29sb3IuRnJvbUFyZ2IoMjQ1LCAyNDcsIDI1MCk7CgogICAgICAgIExhYmVsIGRyb3BBcmVhID0gbmV3IExhYmVsKCk7CiAgICAgICAgZHJvcEFyZWEuTG9jYXRpb24gPSBuZXcgUG9pbnQoMjAsIDIwKTsKICAgICAgICBkcm9wQXJlYS5TaXplID0gbmV3IFNpemUoNTAwLCAxNjApOwogICAgICAgIGRyb3BBcmVhLkJvcmRlclN0eWxlID0gQm9yZGVyU3R5bGUuRml4ZWRTaW5nbGU7CiAgICAgICAgZHJvcEFyZWEuQmFja0NvbG9yID0gQ29sb3IuV2hpdGU7CiAgICAgICAgZHJvcEFyZWEuVGV4dEFsaWduID0gQ29udGVudEFsaWdubWVudC5NaWRkbGVDZW50ZXI7CiAgICAgICAgZHJvcEFyZWEuVGV4dCA9ICLlsIYgWklQIOWOi+e8qeWMheaLluWIsOi/memHjFxyXG5cclxu5Lmf5Y+v5Lul54K55Ye75LiL5pa55oyJ6ZKu6YCJ5oup5paH5Lu2IjsKICAgICAgICBDb250cm9scy5BZGQoZHJvcEFyZWEpOwoKICAgICAgICBCdXR0b24gY2hvb3NlID0gbmV3IEJ1dHRvbigpOwogICAgICAgIGNob29zZS5UZXh0ID0gIumAieaLqSBaSVDigKYiOwogICAgICAgIGNob29zZS5Mb2NhdGlvbiA9IG5ldyBQb2ludCgxMjUsIDIwNSk7CiAgICAgICAgY2hvb3NlLlNpemUgPSBuZXcgU2l6ZSgxNTAsIDQyKTsKICAgICAgICBDb250cm9scy5BZGQoY2hvb3NlKTsKICAgICAgICBCdXR0b24gY2FuY2VsID0gbmV3IEJ1dHRvbigpOwogICAgICAgIGNhbmNlbC5UZXh0ID0gIuWPlua2iCI7CiAgICAgICAgY2FuY2VsLkxvY2F0aW9uID0gbmV3IFBvaW50KDI5NSwgMjA1KTsKICAgICAgICBjYW5jZWwuU2l6ZSA9IG5ldyBTaXplKDEyMCwgNDIpOwogICAgICAgIGNhbmNlbC5EaWFsb2dSZXN1bHQgPSBEaWFsb2dSZXN1bHQuQ2FuY2VsOwogICAgICAgIENvbnRyb2xzLkFkZChjYW5jZWwpOwogICAgICAgIENhbmNlbEJ1dHRvbiA9IGNhbmNlbDsKICAgICAgICBBY2NlcHRCdXR0b24gPSBjaG9vc2U7CgogICAgICAgIGZvcmVhY2ggKENvbnRyb2wgY29udHJvbCBpbiBuZXcgQ29udHJvbFtdIHsgdGhpcywgZHJvcEFyZWEsIGNob29zZSB9KQogICAgICAgIHsKICAgICAgICAgICAgY29udHJvbC5BbGxvd0Ryb3AgPSB0cnVlOwogICAgICAgICAgICBjb250cm9sLkRyYWdFbnRlciArPSBkZWxlZ2F0ZShvYmplY3Qgc2VuZGVyLCBEcmFnRXZlbnRBcmdzIGUpCiAgICAgICAgICAgIHsKICAgICAgICAgICAgICAgIHN0cmluZ1tdIGZpbGVzID0gZS5EYXRhLkdldERhdGEoRGF0YUZvcm1hdHMuRmlsZURyb3ApIGFzIHN0cmluZ1tdOwogICAgICAgICAgICAgICAgYm9vbCB2YWxpZCA9IGZpbGVzICE9IG51bGwgJiYgZmlsZXMuTGVuZ3RoID4gMDsKICAgICAgICAgICAgICAgIGlmIChmaWxlcyAhPSBudWxsKQogICAgICAgICAgICAgICAgICAgIGZvcmVhY2ggKHN0cmluZyBmaWxlIGluIGZpbGVzKQogICAgICAgICAgICAgICAgICAgICAgICB2YWxpZCA9IHZhbGlkICYmIEZpbGUuRXhpc3RzKGZpbGUpICYmCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBTdHJpbmcuRXF1YWxzKFBhdGguR2V0RXh0ZW5zaW9uKGZpbGUpLCAiLnppcCIsIFN0cmluZ0NvbXBhcmlzb24uT3JkaW5hbElnbm9yZUNhc2UpOwogICAgICAgICAgICAgICAgZS5FZmZlY3QgPSB2YWxpZCA/IERyYWdEcm9wRWZmZWN0cy5Db3B5IDogRHJhZ0Ryb3BFZmZlY3RzLk5vbmU7CiAgICAgICAgICAgIH07CiAgICAgICAgICAgIGNvbnRyb2wuRHJhZ0Ryb3AgKz0gZGVsZWdhdGUob2JqZWN0IHNlbmRlciwgRHJhZ0V2ZW50QXJncyBlKQogICAgICAgICAgICB7CiAgICAgICAgICAgICAgICBTZWxlY3RlZFBhdGhzID0gZS5EYXRhLkdldERhdGEoRGF0YUZvcm1hdHMuRmlsZURyb3ApIGFzIHN0cmluZ1tdID8/IG5ldyBzdHJpbmdbMF07CiAgICAgICAgICAgICAgICBEaWFsb2dSZXN1bHQgPSBEaWFsb2dSZXN1bHQuT0s7CiAgICAgICAgICAgICAgICBDbG9zZSgpOwogICAgICAgICAgICB9OwogICAgICAgIH0KICAgICAgICBjaG9vc2UuQ2xpY2sgKz0gZGVsZWdhdGUKICAgICAgICB7CiAgICAgICAgICAgIHVzaW5nIChPcGVuRmlsZURpYWxvZyBkaWFsb2cgPSBuZXcgT3BlbkZpbGVEaWFsb2coKSkKICAgICAgICAgICAgewogICAgICAgICAgICAgICAgZGlhbG9nLlRpdGxlID0gIumAieaLqSBaSVAg5Y6L57yp5YyFIjsKICAgICAgICAgICAgICAgIGRpYWxvZy5GaWx0ZXIgPSAiWklQIOWOi+e8qeWMhSAoKi56aXApfCouemlwIjsKICAgICAgICAgICAgICAgIGRpYWxvZy5NdWx0aXNlbGVjdCA9IHRydWU7CiAgICAgICAgICAgICAgICBkaWFsb2cuSW5pdGlhbERpcmVjdG9yeSA9IGluaXRpYWxEaXJlY3Rvcnk7CiAgICAgICAgICAgICAgICBpZiAoZGlhbG9nLlNob3dEaWFsb2codGhpcykgPT0gRGlhbG9nUmVzdWx0Lk9LKQogICAgICAgICAgICAgICAgewogICAgICAgICAgICAgICAgICAgIFNlbGVjdGVkUGF0aHMgPSBkaWFsb2cuRmlsZU5hbWVzOwogICAgICAgICAgICAgICAgICAgIERpYWxvZ1Jlc3VsdCA9IERpYWxvZ1Jlc3VsdC5PSzsKICAgICAgICAgICAgICAgICAgICBDbG9zZSgpOwogICAgICAgICAgICAgICAgfQogICAgICAgICAgICB9CiAgICAgICAgfTsKICAgICAgICBTaG93biArPSBkZWxlZ2F0ZSB7IFdpbmRvd1N0YXRlID0gRm9ybVdpbmRvd1N0YXRlLk5vcm1hbDsgQWN0aXZhdGUoKTsgfTsKICAgIH0KCiAgICBbU1RBVGhyZWFkXQogICAgc3RhdGljIGludCBNYWluKHN0cmluZ1tdIGFyZ3MpCiAgICB7CiAgICAgICAgaWYgKGFyZ3MuTGVuZ3RoICE9IDIpCiAgICAgICAgICAgIHJldHVybiAxOwogICAgICAgIERpY3Rpb25hcnk8c3RyaW5nLCBvYmplY3Q+IHJlc3VsdCA9IG5ldyBEaWN0aW9uYXJ5PHN0cmluZywgb2JqZWN0PigpOwogICAgICAgIHJlc3VsdFsicGF0aHMiXSA9IG5ldyBzdHJpbmdbMF07CiAgICAgICAgcmVzdWx0WyJlcnJvciJdID0gbnVsbDsKICAgICAgICB0cnkKICAgICAgICB7CiAgICAgICAgICAgIEFwcGxpY2F0aW9uLkVuYWJsZVZpc3VhbFN0eWxlcygpOwogICAgICAgICAgICBBcHBsaWNhdGlvbi5TZXRDb21wYXRpYmxlVGV4dFJlbmRlcmluZ0RlZmF1bHQoZmFsc2UpOwogICAgICAgICAgICB1c2luZyAoUmVzb3VyY2VDc3ZQaWNrZXIgcGlja2VyID0gbmV3IFJlc291cmNlQ3N2UGlja2VyKGFyZ3NbMV0pKQogICAgICAgICAgICB7CiAgICAgICAgICAgICAgICBwaWNrZXIuU2hvd0RpYWxvZygpOwogICAgICAgICAgICAgICAgcmVzdWx0WyJwYXRocyJdID0gcGlja2VyLlNlbGVjdGVkUGF0aHM7CiAgICAgICAgICAgIH0KICAgICAgICB9CiAgICAgICAgY2F0Y2ggKEV4Y2VwdGlvbiBlcnJvcikKICAgICAgICB7CiAgICAgICAgICAgIHJlc3VsdFsiZXJyb3IiXSA9IGVycm9yLk1lc3NhZ2U7CiAgICAgICAgfQogICAgICAgIEZpbGUuV3JpdGVBbGxUZXh0KGFyZ3NbMF0sIG5ldyBKYXZhU2NyaXB0U2VyaWFsaXplcigpLlNlcmlhbGl6ZShyZXN1bHQpLCBuZXcgVVRGOEVuY29kaW5nKGZhbHNlKSk7CiAgICAgICAgcmV0dXJuIHJlc3VsdFsiZXJyb3IiXSA9PSBudWxsID8gMCA6IDE7CiAgICB9Cn0K'


def run_with_shell_token(command, working_directory):
    """Run the picker with Explorer's token so Explorer can drag files into it.

    This only lowers an elevated launcher's UI to the desktop shell's context;
    no account, privilege, UAC or other system setting is changed.
    """
    import ctypes
    from ctypes import wintypes

    class StartupInfo(ctypes.Structure):
        _fields_ = [
            ('cb', wintypes.DWORD), ('lpReserved', wintypes.LPWSTR),
            ('lpDesktop', wintypes.LPWSTR), ('lpTitle', wintypes.LPWSTR),
            ('dwX', wintypes.DWORD), ('dwY', wintypes.DWORD),
            ('dwXSize', wintypes.DWORD), ('dwYSize', wintypes.DWORD),
            ('dwXCountChars', wintypes.DWORD), ('dwYCountChars', wintypes.DWORD),
            ('dwFillAttribute', wintypes.DWORD), ('dwFlags', wintypes.DWORD),
            ('wShowWindow', wintypes.WORD), ('cbReserved2', wintypes.WORD),
            ('lpReserved2', ctypes.POINTER(wintypes.BYTE)),
            ('hStdInput', wintypes.HANDLE), ('hStdOutput', wintypes.HANDLE),
            ('hStdError', wintypes.HANDLE),
        ]

    class ProcessInfo(ctypes.Structure):
        _fields_ = [('hProcess', wintypes.HANDLE), ('hThread', wintypes.HANDLE),
                    ('dwProcessId', wintypes.DWORD), ('dwThreadId', wintypes.DWORD)]

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    security = ctypes.WinDLL('advapi32', use_last_error=True)
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetShellWindow.restype = wintypes.HWND
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    security.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    security.DuplicateTokenEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p,
                                        ctypes.c_int, ctypes.c_int, ctypes.POINTER(wintypes.HANDLE)]
    security.CreateProcessWithTokenW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPWSTR,
        wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
        ctypes.POINTER(StartupInfo), ctypes.POINTER(ProcessInfo),
    ]
    handles, started = [], False
    try:
        shell = user.GetShellWindow()
        pid = wintypes.DWORD()
        if shell:
            user.GetWindowThreadProcessId(shell, ctypes.byref(pid))
        else:
            # Background hosts may have a private desktop with no shell window.
            # Find Explorer in this session rather than inheriting that desktop.
            kernel.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
            session = wintypes.DWORD()
            kernel.ProcessIdToSessionId(os.getpid(), ctypes.byref(session))
            tasklist = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/tasklist.exe'
            listing = subprocess.run([str(tasklist), '/FI', 'IMAGENAME eq explorer.exe', '/FO', 'CSV', '/NH'],
                                     capture_output=True, text=True, errors='replace',
                                     creationflags=subprocess.CREATE_NO_WINDOW, check=False)
            for row in csv.reader(io.StringIO(listing.stdout)):
                if len(row) < 2 or row[0].lower() != 'explorer.exe' or not row[1].isdigit():
                    continue
                candidate_session = wintypes.DWORD()
                if (kernel.ProcessIdToSessionId(int(row[1]), ctypes.byref(candidate_session))
                        and candidate_session.value == session.value):
                    pid.value = int(row[1])
                    break
        if not pid.value:
            return False
        process = kernel.OpenProcess(0x1000, False, pid.value)
        if not process:
            return False
        handles.append(process)
        token, primary = wintypes.HANDLE(), wintypes.HANDLE()
        if not security.OpenProcessToken(process, 0x0002 | 0x0008, ctypes.byref(token)):
            return False
        handles.append(token)
        if not security.DuplicateTokenEx(token, 0x02000000, None, 2, 1, ctypes.byref(primary)):
            return False
        handles.append(primary)
        startup, info = StartupInfo(), ProcessInfo()
        startup.cb = ctypes.sizeof(startup)
        startup.lpDesktop = 'winsta0\\default'
        startup.dwFlags = 0x00000001  # STARTF_USESHOWWINDOW
        startup.wShowWindow = 1  # SW_SHOWNORMAL: this is an interactive picker.
        if not security.CreateProcessWithTokenW(
                primary, 0, None, ctypes.create_unicode_buffer(subprocess.list2cmdline(command)),
                0x08000000, None, str(working_directory), ctypes.byref(startup), ctypes.byref(info)):
            return False
        started = True
        handles.extend([info.hProcess, info.hThread])
        kernel.WaitForSingleObject(info.hProcess, 0xFFFFFFFF)
        return True
    except OSError:
        return started
    finally:
        for handle in reversed(handles):
            kernel.CloseHandle(handle)


def choose_zip_files():
    directory = Path(os.environ.get('RESOURCE_CSV_LAUNCHER_PATH') or __file__).resolve().parent
    frameworks = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'Microsoft.NET'
    compiler = next((frameworks / version / 'v4.0.30319/csc.exe'
                     for version in ('Framework64', 'Framework')
                     if (frameworks / version / 'v4.0.30319/csc.exe').is_file()), None)
    if compiler is None:
        raise ConversionError('缺少 Windows 窗口组件；请将 ZIP 直接拖到 BAT 文件图标上转换。')
    with tempfile.TemporaryDirectory(prefix='resource-csv-picker-') as workspace:
        result_path = Path(workspace) / 'selection.json'
        source_path = Path(workspace) / 'ResourceCsvPicker.cs'
        executable = Path(workspace) / 'ResourceCsvPicker.exe'
        if PICKER_SOURCE_BASE64.startswith('__'):
            picker_source = Path(__file__).with_name('resource_csv_picker.cs').read_text(encoding='utf-8')
        else:
            picker_source = base64.b64decode(PICKER_SOURCE_BASE64).decode('utf-8')
        source_path.write_text(picker_source, encoding='utf-8-sig')
        compiled = subprocess.run([
            str(compiler), '/nologo', '/target:winexe', '/out:' + str(executable),
            '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
            '/reference:System.Web.Extensions.dll', str(source_path),
        ], capture_output=True, text=True, errors='replace', check=False,
            creationflags=subprocess.CREATE_NO_WINDOW)
        if compiled.returncode:
            raise ConversionError('文件选择窗口创建失败；请将 ZIP 直接拖到 BAT 文件图标上转换。')
        command = [str(executable), str(result_path), str(directory)]
        if not run_with_shell_token(command, directory):
            startup = subprocess.STARTUPINFO()
            startup.dwFlags = subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 1
            subprocess.run(command, check=False, startupinfo=startup)
        if not result_path.is_file():
            raise ConversionError('文件选择窗口未能正常启动，请将 ZIP 直接拖到 BAT 文件图标上重试。')
        result = json.loads(result_path.read_text(encoding='utf-8-sig'))
        if result.get('error'):
            raise ConversionError('文件选择窗口错误：' + str(result['error']))
        return [Path(value) for value in result.get('paths', [])]


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    limit = sys.maxsize
    while True:
        try:
            csv.field_size_limit(limit)
            break
        except OverflowError:
            limit //= 10
    parser = argparse.ArgumentParser(description='完整资源库 ZIP 转换为可导入的 CSV。')
    parser.add_argument('files', nargs='*', help='可选：指定 ZIP 路径；SH 默认处理脚本目录下的全部 ZIP。')
    args = parser.parse_args()
    if args.files:
        sources = [Path(value) for value in args.files]
    elif os.environ.get('RESOURCE_CSV_LAUNCHER_MODE') == 'bat':
        value = os.environ.get('RESOURCE_CSV_INPUT_PATH')
        if not value and os.name == 'nt' and os.environ.get('RESOURCE_CSV_CONSOLE_INPUT') != '1':
            print('请在弹出的窗口拖入 ZIP，或点击“选择 ZIP”。', flush=True)
            try:
                sources = choose_zip_files()
            except (ConversionError, OSError, ValueError) as exc:
                print('失败：' + str(exc), file=sys.stderr)
                return 1
            if not sources:
                print('已取消。')
                return 0
        else:
            value = value or input('请输入完整 ZIP 路径，然后按回车：\n').strip()
            if not value:
                return 0
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            sources = [Path(value)]
    else:
        directory = Path(os.environ.get('RESOURCE_CSV_LAUNCHER_PATH') or __file__).resolve().parent
        sources = sorted((path for path in directory.iterdir() if path.is_file() and path.suffix.lower() == '.zip'),
                         key=lambda path: path.name.lower())
        if not sources:
            print('脚本目录下没有 ZIP 文件：' + str(directory))
            return 0
    succeeded, failed = 0, 0
    for source in sources:
        print('\n正在转换：' + str(source), flush=True)
        try:
            destination, count, protocols = convert_zip(source)
            print('完成：%d 条资源（ED2K %d，磁力 %d）' % (count, protocols['ed2k'], protocols['magnet']))
            print('CSV：' + str(destination), flush=True)
            succeeded += 1
        except (ConversionError, OSError, ValueError, csv.Error, zipfile.BadZipFile, RuntimeError) as exc:
            print('失败：' + str(exc), file=sys.stderr, flush=True)
            failed += 1
    print('\n转换结束：成功 %d 个压缩包，失败 %d 个。' % (succeeded, failed))
    return 1 if failed else 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (KeyboardInterrupt, EOFError):
        print('\n已取消。')
        raise SystemExit(130)

# __RESOURCE_CSV_END__
__RESOURCE_CSV_EMBEDDED_PYTHON__
