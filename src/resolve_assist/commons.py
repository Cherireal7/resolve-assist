"""Wikimedia Commons: find images and download them with their licence recorded.

Only the public API is used. Requests carry a generic client name and nothing about the user.
"""

from __future__ import annotations

import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://commons.wikimedia.org/w/api.php"
AGENT = "resolve-assist/0.2 (local video tool)"
MAX_BYTES = 40 * 1024 * 1024
IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}


def _get(url: str, binary: bool = False, tries: int = 4):
    for attempt in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": AGENT})
        try:
            with urllib.request.urlopen(req, timeout=40) as resp:
                data = resp.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    raise ValueError("the file is larger than 40 MB")
                return (data, resp.headers.get_content_type()) if binary else json.loads(data)
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 503) and attempt + 1 < tries:
                time.sleep(2.0 * (attempt + 1) ** 2)     # the API asks anonymous clients to slow down
                continue
            raise
    raise RuntimeError("Wikimedia Commons did not answer")


def _plain(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", value or ""))).strip()[:200]


def _info(page: dict) -> dict | None:
    ii = (page.get("imageinfo") or [None])[0]
    if not ii:
        return None
    meta = {k: (v.get("value") if isinstance(v, dict) else "") for k, v in (ii.get("extmetadata") or {}).items()}
    licence = _plain(meta.get("LicenseShortName", "")) or "unknown"
    low = licence.lower()
    return {"title": page.get("title", ""), "source": ii.get("descriptionurl", ""), "license": licence,
            "author": _plain(meta.get("Artist", "")) or "unknown", "width": ii.get("width"), "height": ii.get("height"),
            "mime": ii.get("mime", ""), "thumb": ii.get("thumburl") or ii.get("url", ""),
            "free": low.startswith(("public domain", "cc0", "pd")),
            "share_alike": "sa" in re.split(r"[\s-]+", low),
            "attribution": low.startswith("cc by")}


def search(query: str, limit: int = 12) -> list[dict]:
    """Images matching the words, each with licence, author and a preview URL."""
    q = urllib.parse.urlencode({"action": "query", "format": "json", "generator": "search", "gsrsearch": query, "gsrnamespace": 6,
                                "gsrlimit": max(1, min(30, int(limit))), "prop": "imageinfo", "iiprop": "url|extmetadata|size|mime",
                                "iiurlwidth": 480})
    pages = (_get(f"{API}?{q}").get("query") or {}).get("pages") or {}
    out = [i for i in (_info(p) for p in sorted(pages.values(), key=lambda p: p.get("index", 0))) if i]
    return [i for i in out if i["mime"] in IMAGE_TYPES or i["mime"] in ("image/svg+xml", "image/tiff")]


def fetch(title: str, dest: Path, width: int = 1920) -> dict:
    """Download one Commons file (scaled to `width`) into dest and return its credit entry."""
    title = urllib.parse.unquote(title.strip().rsplit("/", 1)[-1])
    if not title.lower().startswith("file:"):
        title = "File:" + title
    q = urllib.parse.urlencode({"action": "query", "format": "json", "titles": title, "prop": "imageinfo",
                                "iiprop": "url|extmetadata|size|mime", "iiurlwidth": max(320, min(4000, int(width)))})
    pages = (_get(f"{API}?{q}").get("query") or {}).get("pages") or {}
    info = next((i for i in (_info(p) for p in pages.values()) if i), None)
    if not info or not info["thumb"]:
        raise ValueError(f"not found on Wikimedia Commons: {title}")
    if not urllib.parse.urlparse(info["thumb"]).netloc.endswith("wikimedia.org"):
        raise ValueError("unexpected download address")
    data, ctype = _get(info["thumb"], binary=True)
    ext = IMAGE_TYPES.get(ctype)
    if not ext:
        raise ValueError(f"not an image that can be used directly ({ctype})")
    stem = re.sub(r"[^A-Za-z0-9]+", "-", title.split(":", 1)[1].rsplit(".", 1)[0]).strip("-").lower()[:60] or "commons-image"
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"{stem}{ext}"
    n = 1
    while path.exists():
        path = dest / f"{stem}-{n}{ext}"
        n += 1
    path.write_bytes(data)
    return {"path": str(path), **{k: info[k] for k in ("source", "license", "author", "free", "share_alike", "attribution")}}
