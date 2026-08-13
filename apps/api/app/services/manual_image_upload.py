from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlparse

import httpx


logger = logging.getLogger(__name__)


#: image-proxy 取图的体积上限，必须和 apps/web/app/api/image-proxy/route.ts
#: 里的 MAX_IMAGE_BYTES 保持一致。前台展示任何图片都要经过 image-proxy，
#: 所以「传得进来、代理取不回来」的图等于上传成功即坏图——这两个数字原先
#: 一个 10MB 一个 8MB，中间 2MB 是个静默的坏图区间。
#: 两边的一致性由 tests/test_image_proxy_guard.py 锁住，改一个就要改另一个。
IMAGE_PROXY_MAX_BYTES = 8 * 1024 * 1024


ALLOWED_IMAGE_TYPES = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF",),
    "image/gif": (b"GIF87a", b"GIF89a"),
}


class ImageUploadError(RuntimeError):
    def __init__(self, code: str, detail: str, status_code: int):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code


def _bool_env(name: str, default: bool) -> str:
    value = os.getenv(name, "true" if default else "false").strip().lower()
    return "true" if value in {"1", "true", "yes", "on"} else "false"


def max_upload_bytes() -> int:
    """上传体积上限。

    可以用 IMAGE_UPLOAD_MAX_BYTES 调低，但不接受高过 IMAGE_PROXY_MAX_BYTES 的值：
    上限一旦超过代理取图上限，多出来的那一段传上去也展示不了。配置写高了会
    被夹到代理上限并记一条 warning，而不是静默生效。
    """
    raw = os.getenv("IMAGE_UPLOAD_MAX_BYTES", "").strip()
    if not raw:
        return IMAGE_PROXY_MAX_BYTES
    try:
        configured = int(raw)
    except ValueError:
        logger.warning("IMAGE_UPLOAD_MAX_BYTES 不是整数(%r)，按 %d 处理", raw, IMAGE_PROXY_MAX_BYTES)
        return IMAGE_PROXY_MAX_BYTES
    if configured > IMAGE_PROXY_MAX_BYTES:
        logger.warning(
            "IMAGE_UPLOAD_MAX_BYTES=%d 超过 image-proxy 取图上限 %d，已夹到上限："
            "超出部分即使上传成功也无法在前台展示",
            configured,
            IMAGE_PROXY_MAX_BYTES,
        )
        return IMAGE_PROXY_MAX_BYTES
    return max(configured, 0)


def _validate_image(data: bytes, content_type: str) -> None:
    if not data:
        raise ImageUploadError("unsupported_image_type", "empty image", 415)
    signatures = ALLOWED_IMAGE_TYPES.get(content_type)
    if not signatures:
        raise ImageUploadError("unsupported_image_type", "unsupported image type", 415)
    if content_type == "image/webp":
        valid = data.startswith(b"RIFF") and data[8:12] == b"WEBP"
    else:
        valid = any(data.startswith(signature) for signature in signatures)
    if not valid:
        raise ImageUploadError("unsupported_image_type", "file signature does not match MIME", 415)


def upload_image_to_host(
    *,
    filename: str,
    content_type: str,
    data: bytes,
    client: Any = None,
) -> str:
    if len(data) > max_upload_bytes():
        raise ImageUploadError("image_too_large", "image exceeds configured size limit", 413)
    _validate_image(data, content_type)
    base_url = os.getenv("IMAGE_HOST_BASE_URL", "https://img.suversal.com/upload").strip()
    auth_code = os.getenv("IMAGE_HOST_AUTH_CODE", "").strip()
    if not auth_code:
        raise ImageUploadError("image_host_failed", "image host is not configured", 502)
    params = {
        "authCode": auth_code,
        "uploadChannel": os.getenv("IMAGE_HOST_UPLOAD_CHANNEL", "telegram"),
        "channelName": os.getenv("IMAGE_HOST_CHANNEL_NAME", "Tel_Channel"),
        "serverCompress": _bool_env("IMAGE_HOST_SERVER_COMPRESS", True),
        "autoRetry": _bool_env("IMAGE_HOST_AUTO_RETRY", True),
        "uploadNameType": os.getenv("IMAGE_HOST_NAME_TYPE", "short"),
        "returnFormat": os.getenv("IMAGE_HOST_RETURN_FORMAT", "full"),
    }
    upload_folder = os.getenv("IMAGE_HOST_UPLOAD_FOLDER", "").strip()
    if upload_folder:
        params["uploadFolder"] = upload_folder
    owns_client = client is None
    http_client = client or httpx.Client(timeout=30.0)
    try:
        response = http_client.post(
            base_url,
            params=params,
            files={"file": (filename or "image", data, content_type)},
        )
    except Exception as exc:
        raise ImageUploadError("image_host_failed", "image host request failed", 502) from exc
    finally:
        if owns_client:
            http_client.close()
    if not response.is_success:
        raise ImageUploadError("image_host_failed", "image host rejected upload", 502)
    try:
        payload = response.json()
        src = payload[0]["src"]
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        raise ImageUploadError("image_host_failed", "image host returned an invalid response", 502) from exc
    parsed = urlparse(str(src))
    if parsed.scheme != "https" or not parsed.netloc:
        raise ImageUploadError("image_host_failed", "image host returned a non-HTTPS URL", 502)
    return str(src)
