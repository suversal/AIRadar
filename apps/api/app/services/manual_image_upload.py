from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

import httpx


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
    max_bytes = int(os.getenv("IMAGE_UPLOAD_MAX_BYTES", str(10 * 1024 * 1024)))
    if len(data) > max_bytes:
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
