from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from html import unescape
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote, urljoin, urlsplit

from app.crawlers.base import clean_text

README_PARAGRAPH_LIMIT = 12
README_CHAR_LIMIT = 6000
README_MARKDOWN_CHAR_LIMIT = 80_000
CHINESE_README_PRIORITY = [
    "README_zh.md",
    "README_CN.md",
    "README.zh-CN.md",
    "README-zh.md",
    "README.zh.md",
    "README_zh-CN.md",
    "README_cn.md",
]

GITHUB_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HTML_IMG_RE = re.compile(r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"'][^>]*>", re.IGNORECASE)
HTML_ALT_RE = re.compile(r"\balt=[\"']([^\"']*)[\"']", re.IGNORECASE)
FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)


def repo_path_from_github_url(value: str | None) -> str:
    if not value:
        return ""
    value = value.strip()
    if GITHUB_REPO_RE.match(value):
        return value
    parts = urlsplit(value)
    if parts.netloc.lower() not in {"github.com", "www.github.com"}:
        return ""
    segments = [segment for segment in parts.path.split("/") if segment]
    if len(segments) < 2:
        return ""
    repo_path = f"{segments[0]}/{segments[1]}"
    return repo_path if GITHUB_REPO_RE.match(repo_path) else ""


def _branch_and_readme_dir(download_url: str, repo_path: str) -> tuple[str, str]:
    parts = urlsplit(download_url)
    path_segments = [segment for segment in parts.path.split("/") if segment]
    owner, repo = repo_path.split("/", 1)
    if (
        parts.netloc.lower() == "raw.githubusercontent.com"
        and len(path_segments) >= 4
        and path_segments[0].lower() == owner.lower()
        and path_segments[1].lower() == repo.lower()
    ):
        branch = path_segments[2]
        readme_dir = str(PurePosixPath(*path_segments[3:-1])) if path_segments[3:-1] else ""
        return branch, readme_dir
    return "main", ""


def _absolute_readme_asset_url(url: str, *, repo_path: str, download_url: str) -> str:
    url = url.strip()
    if not url:
        return ""
    parts = urlsplit(url)
    if parts.scheme in {"http", "https", "data"}:
        return url
    branch, readme_dir = _branch_and_readme_dir(download_url, repo_path)
    owner, repo = repo_path.split("/", 1)
    raw_base = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/"
    if url.startswith("/"):
        return urljoin(raw_base, url.lstrip("/"))
    if readme_dir:
        return urljoin(f"{raw_base}{readme_dir}/", url)
    return urljoin(raw_base, url)


def _absolute_readme_link_url(url: str, *, repo_path: str, download_url: str) -> str:
    url = url.strip()
    if not url:
        return ""
    parts = urlsplit(url)
    if parts.scheme or parts.netloc or url.startswith("#"):
        return url
    branch, readme_dir = _branch_and_readme_dir(download_url, repo_path)
    owner, repo = repo_path.split("/", 1)
    github_base = f"https://github.com/{owner}/{repo}/blob/{branch}/"
    if url.startswith("/"):
        return urljoin(github_base, url.lstrip("/"))
    if readme_dir:
        return urljoin(f"{github_base}{readme_dir}/", url)
    return urljoin(github_base, url)


def _rewrite_readme_markdown_urls(markdown: str, *, repo_path: str, download_url: str) -> str:
    def replace_image(match: re.Match[str]) -> str:
        alt = match.group(1)
        url = match.group(2)
        absolute_url = _absolute_readme_asset_url(url, repo_path=repo_path, download_url=download_url)
        return f"![{alt}]({absolute_url})" if absolute_url else match.group(0)

    def replace_link(match: re.Match[str]) -> str:
        label = match.group(1)
        url = match.group(2)
        absolute_url = _absolute_readme_link_url(url, repo_path=repo_path, download_url=download_url)
        return f"[{label}]({absolute_url})" if absolute_url else match.group(0)

    def replace_html_img(match: re.Match[str]) -> str:
        tag = match.group(0)
        url = match.group(1)
        absolute_url = _absolute_readme_asset_url(url, repo_path=repo_path, download_url=download_url)
        return tag.replace(url, absolute_url, 1) if absolute_url else tag

    markdown = MARKDOWN_IMAGE_RE.sub(replace_image, markdown)
    markdown = MARKDOWN_LINK_RE.sub(replace_link, markdown)
    return HTML_IMG_RE.sub(replace_html_img, markdown)


def _limit_readme_markdown(markdown: str, *, char_limit: int = README_MARKDOWN_CHAR_LIMIT) -> str:
    markdown = markdown.strip()
    if len(markdown) <= char_limit:
        return markdown
    return markdown[:char_limit].rstrip()


def _markdown_images(chunk: str, *, repo_path: str, download_url: str) -> list[dict[str, str]]:
    images: list[dict[str, str]] = []
    for alt, url in MARKDOWN_IMAGE_RE.findall(chunk):
        absolute_url = _absolute_readme_asset_url(url, repo_path=repo_path, download_url=download_url)
        if absolute_url:
            images.append({"type": "image", "url": absolute_url, "alt": clean_text(alt), "caption": ""})
    for match in HTML_IMG_RE.finditer(chunk):
        tag = match.group(0)
        url = match.group(1)
        alt_match = HTML_ALT_RE.search(tag)
        absolute_url = _absolute_readme_asset_url(url, repo_path=repo_path, download_url=download_url)
        if absolute_url:
            images.append(
                {
                    "type": "image",
                    "url": absolute_url,
                    "alt": clean_text(alt_match.group(1) if alt_match else ""),
                    "caption": "",
                }
            )
    return images


def _markdown_to_text(chunk: str) -> str:
    chunk = MARKDOWN_IMAGE_RE.sub(" ", chunk)
    chunk = HTML_IMG_RE.sub(" ", chunk)
    chunk = re.sub(r"<[^>]+>", " ", chunk)
    chunk = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", chunk)
    chunk = re.sub(r"^\s{0,3}#{1,6}\s*", "", chunk, flags=re.MULTILINE)
    chunk = re.sub(r"^\s{0,3}>\s?", "", chunk, flags=re.MULTILINE)
    chunk = re.sub(r"^\s*[-*+]\s+", "", chunk, flags=re.MULTILINE)
    chunk = re.sub(r"^\s*\d+\.\s+", "", chunk, flags=re.MULTILINE)
    chunk = re.sub(r"[*_`~]+", "", chunk)
    return clean_text(unescape(chunk))


def markdown_to_original_payload(
    markdown: str,
    *,
    repo_path: str,
    download_url: str,
    paragraph_limit: int = README_PARAGRAPH_LIMIT,
    char_limit: int = README_CHAR_LIMIT,
) -> dict[str, Any]:
    markdown = FENCED_CODE_RE.sub("\n", markdown)
    chunks = [chunk.strip() for chunk in re.split(r"\n\s*\n", markdown) if chunk.strip()]
    paragraphs: list[str] = []
    blocks: list[dict[str, str]] = []
    images: list[dict[str, str]] = []
    seen_images: set[str] = set()
    used_chars = 0

    for chunk in chunks:
        for image in _markdown_images(chunk, repo_path=repo_path, download_url=download_url):
            if image["url"] in seen_images:
                continue
            seen_images.add(image["url"])
            images.append({key: image[key] for key in ("url", "alt", "caption")})
            blocks.append(image)

        if len(paragraphs) >= paragraph_limit or used_chars >= char_limit:
            continue

        text = _markdown_to_text(chunk)
        if not text:
            continue
        remaining = char_limit - used_chars
        if remaining <= 0:
            continue
        if len(text) > remaining:
            text = text[:remaining].strip()
        if not text:
            continue
        paragraphs.append(text)
        blocks.append({"type": "paragraph", "text": text})
        used_chars += len(text)

    return {
        "original_content": "\n\n".join(paragraphs),
        "original_paragraphs": paragraphs,
        "original_images": images,
        "original_blocks": blocks,
    }


def _readme_failure(status: str, error: str = "") -> dict[str, str]:
    payload = {"readme_status": status}
    if error:
        payload["readme_error"] = error[:200]
    return payload


def _github_headers(github_token: str | None = None) -> dict[str, str]:
    token = github_token if github_token is not None else os.getenv("GITHUB_TOKEN")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "SuversalAIRadar/0.1",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _github_json_request(url: str, github_token: str | None = None) -> Any:
    request = urllib.request.Request(url, headers=_github_headers(github_token))
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _selected_chinese_readme(root_payload: Any) -> dict[str, Any] | None:
    if not isinstance(root_payload, list):
        return None

    files_by_name = {}
    for item in root_payload:
        if not isinstance(item, dict) or item.get("type") != "file":
            continue
        name = str(item.get("name") or "")
        if name:
            files_by_name[name.lower()] = item

    for filename in CHINESE_README_PRIORITY:
        match = files_by_name.get(filename.lower())
        if match:
            return match
    return None


def _decode_readme_payload(
    api_payload: dict[str, Any],
    *,
    repo_path: str,
    readme_language: str,
    readme_selection: str,
) -> dict[str, Any]:
    if api_payload.get("encoding") != "base64" or not api_payload.get("content"):
        return _readme_failure("failed", "GitHub README payload missing base64 content")

    try:
        markdown = base64.b64decode(str(api_payload["content"]).replace("\n", "")).decode(
            "utf-8",
            errors="replace",
        )
    except Exception as exc:
        return _readme_failure("failed", f"failed to decode README: {exc}")

    download_url = str(api_payload.get("download_url") or "")
    html_url = str(api_payload.get("html_url") or "")
    readme_name = str(api_payload.get("name") or "").strip()
    original_markdown = _limit_readme_markdown(
        _rewrite_readme_markdown_urls(
            markdown,
            repo_path=repo_path,
            download_url=download_url,
        )
    )
    original_payload = markdown_to_original_payload(
        markdown,
        repo_path=repo_path,
        download_url=download_url,
    )
    if not original_payload["original_paragraphs"]:
        return _readme_failure("failed", "README has no readable paragraphs")
    return {
        "readme_status": "ok",
        "readme_url": download_url or html_url,
        "readme_html_url": html_url,
        "readme_name": readme_name,
        "readme_language": readme_language,
        "readme_selection": readme_selection,
        "original_markdown": original_markdown,
        **original_payload,
    }


def _fetch_default_readme(repo_path: str, github_token: str | None = None) -> dict[str, Any]:
    owner, repo = repo_path.split("/", 1)
    url = f"https://api.github.com/repos/{quote(owner)}/{quote(repo)}/readme"
    api_payload = _github_json_request(url, github_token)
    return _decode_readme_payload(
        api_payload,
        repo_path=repo_path,
        readme_language="zh" if str(api_payload.get("name") or "").lower() in {
            item.lower() for item in CHINESE_README_PRIORITY
        } else "en",
        readme_selection="default_readme",
    )


def fetch_github_readme(repo_path: str, github_token: str | None = None) -> dict[str, Any]:
    repo_path = repo_path_from_github_url(repo_path)
    if not repo_path:
        return _readme_failure("skipped", "missing GitHub repo path")

    owner, repo = repo_path.split("/", 1)
    root_url = f"https://api.github.com/repos/{quote(owner)}/{quote(repo)}/contents"

    try:
        root_payload = _github_json_request(root_url, github_token)
    except urllib.error.HTTPError as exc:
        root_payload = None
        root_error = f"GitHub README root contents request failed: {exc.code} {exc.read().decode('utf-8', errors='replace')}"
    except Exception as exc:
        root_payload = None
        root_error = str(exc)
    else:
        root_error = ""

    # 中文优先探测结论：failed = 这次没探成（限流/超时），下轮要重试；
    # none = 确认过仓库没有中文 README，结果是终态
    zh_probe = "failed" if root_payload is None else "none"

    selected_readme = _selected_chinese_readme(root_payload)
    if selected_readme:
        selected_url = str(selected_readme.get("url") or "")
        if selected_url:
            try:
                selected_payload = _github_json_request(selected_url, github_token)
                selected_result = _decode_readme_payload(
                    selected_payload,
                    repo_path=repo_path,
                    readme_language="zh",
                    readme_selection="preferred_zh_readme",
                )
                if selected_result.get("readme_status") == "ok":
                    selected_result["readme_zh_probe"] = "ok"
                    return selected_result
            except Exception:
                pass
        # 中文版明明存在却没抓成，同样要重试
        zh_probe = "failed"

    try:
        result = _fetch_default_readme(repo_path, github_token)
        if result.get("readme_status") == "ok":
            result["readme_zh_probe"] = zh_probe
        return result
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        detail = f"GitHub README request failed: {exc.code} {body}"
        if root_error:
            detail = f"{detail}; root contents: {root_error}"
        return _readme_failure("failed", detail)
    except Exception as exc:
        detail = str(exc)
        if root_error:
            detail = f"{detail}; root contents: {root_error}"
        return _readme_failure("failed", detail)
