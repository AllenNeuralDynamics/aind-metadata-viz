"""Fetch Allen Institute headshot images for all authors in the contributions table.

Steps
-----
1. List every project stored under s3://aind-scratch-data/contributions-app/
2. Load the latest version of each project and collect all unique author names.
3. For each author, derive the person-page slug and try
      https://alleninstitute.org/person/{slug}/
4. Parse the HTML for a .webp image (headshot).
5. Upload the image bytes to
      s3://aind-scratch-data/contributions-app/images/{author_name}.webp
6. Print a summary of found / not-found authors.

Usage
-----
    python scripts/fetch_author_images.py
"""

import sys
import unicodedata
from pathlib import Path

import json

import boto3
from botocore.exceptions import ClientError
import requests
from bs4 import BeautifulSoup

_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from aind_metadata_viz.contributions.store import (
    _S3_BUCKET,
    _S3_PREFIX,
    _get_json,
)

_IMAGES_PREFIX = f"{_S3_PREFIX}/images"
_ALLEN_BASE = "https://alleninstitute.org/person"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def _s3():
    return boto3.client("s3")


def _list_all_project_keys() -> list[str]:
    """Return the S3 key of the latest version object for every project."""
    s3 = _s3()
    paginator = s3.get_paginator("list_objects_v2")
    project_latest: dict[str, str] = {}
    for page in paginator.paginate(Bucket=_S3_BUCKET, Prefix=f"{_S3_PREFIX}/"):
        for obj in page.get("Contents", []):
            key: str = obj["Key"]
            parts = key[len(f"{_S3_PREFIX}/"):].split("/")
            if len(parts) < 2 or parts[0].startswith("_"):
                continue
            project_id = parts[0]
            current = project_latest.get(project_id, "")
            if key > current:
                project_latest[project_id] = key
    return list(project_latest.values())


def _collect_authors(keys: list[str]) -> set[str]:
    names: set[str] = set()
    for key in keys:
        obj = _get_json(key)
        if not obj:
            continue
        raw = obj.get("data", "{}")
        data = json.loads(raw) if isinstance(raw, str) else raw
        for contributor in data.get("contributors", []):
            author = contributor.get("author", {})
            name = author.get("name", "").strip()
            if name:
                names.add(name)
    return names


def _name_to_slug(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    slug = ascii_name.lower().strip()
    for ch in (".", ",", "'", '"', "(", ")", "[", "]"):
        slug = slug.replace(ch, "")
    slug = slug.replace(" ", "-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug


def _find_image_url(page_url: str) -> str | None:
    """Return the src of the profile headshot (class='u-image-cover') or None."""
    try:
        resp = requests.get(page_url, headers=_HEADERS, timeout=15)
    except requests.RequestException as exc:
        print(f"    network error fetching {page_url}: {exc}")
        return None
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        print(f"    HTTP {resp.status_code} for {page_url}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    img = soup.find("img", class_="u-image-cover")
    if img:
        return img.get("src") or None
    return None


_EXT_CONTENT_TYPE = {
    ".webp": "image/webp",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".avif": "image/avif",
    ".gif": "image/gif",
}


def _upload_image(author_name: str, image_bytes: bytes, image_url: str) -> str:
    ext = Path(image_url.split("?")[0]).suffix.lower() or ".jpg"
    content_type = _EXT_CONTENT_TYPE.get(ext, "image/jpeg")
    key = f"{_IMAGES_PREFIX}/{author_name}{ext}"
    _s3().put_object(
        Bucket=_S3_BUCKET,
        Key=key,
        Body=image_bytes,
        ContentType=content_type,
    )
    return key


def main():
    print("Listing projects in s3://aind-scratch-data/contributions-app/ ...")
    keys = _list_all_project_keys()
    print(f"  Found {len(keys)} project(s).")

    print("Collecting author names ...")
    authors = _collect_authors(keys)
    print(f"  Found {len(authors)} unique author(s).\n")

    found: list[str] = []
    not_found: list[str] = []

    for author_name in sorted(authors):
        slug = _name_to_slug(author_name)
        page_url = f"{_ALLEN_BASE}/{slug}/"
        print(f"  {author_name}  →  {page_url}")
        img_url = _find_image_url(page_url)
        if not img_url:
            print(f"    no image found")
            not_found.append(author_name)
            continue
        if img_url.startswith("//"):
            img_url = "https:" + img_url
        elif img_url.startswith("/"):
            img_url = "https://alleninstitute.org" + img_url
        try:
            img_resp = requests.get(img_url, headers=_HEADERS, timeout=30)
            img_resp.raise_for_status()
        except requests.RequestException as exc:
            print(f"    failed to download image: {exc}")
            not_found.append(author_name)
            continue
        s3_key = _upload_image(author_name, img_resp.content, img_url)
        print(f"    uploaded → s3://{_S3_BUCKET}/{s3_key}")
        found.append(author_name)

    print("\n" + "=" * 60)
    print(f"FOUND ({len(found)}):")
    for name in found:
        print(f"  ✓  {name}")
    print(f"\nNOT FOUND ({len(not_found)}):")
    for name in not_found:
        print(f"  ✗  {name}")


if __name__ == "__main__":
    main()
