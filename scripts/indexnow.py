"""Tell search engines which pages changed, via IndexNow (https://www.indexnow.org).

Run after a deploy: `uv run python -m scripts.indexnow [--dry-run]`. It reads
build/sitemap.xml, keeps the URLs whose <lastmod> falls within the last
FRESH_DAYS days and POSTs them to api.indexnow.org, which shares one submission
with Bing, Yandex, Naver, Seznam and the other IndexNow engines. Google does not
use IndexNow (and retired its sitemap ping endpoint), so it just reads the
sitemap on its own schedule.

The key is the single 32-hex-character static/<key>.txt whose content is the
key itself; it is served at https://vilf.org/<key>.txt so the engines can verify
the submission. The key is public by design.

This script never exits non-zero: a failed notification must not fail a deploy.
"""

import re
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path

import click
import requests

HOST = "vilf.org"
ENDPOINT = "https://api.indexnow.org/indexnow"
SITEMAP = Path("build/sitemap.xml")
STATIC = Path("static")
NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
KEY_RE = re.compile(r"^[0-9a-f]{32}$")
FRESH_DAYS = 2


def find_key(static=STATIC) -> str | None:
    """Return the IndexNow key from static/<key>.txt, or None if there is not exactly one."""
    files = [p for p in Path(static).glob("*.txt") if KEY_RE.match(p.stem)]
    if len(files) != 1:
        return None
    return files[0].read_text(encoding="utf-8").strip()


def fresh_urls(sitemap=SITEMAP, days=FRESH_DAYS, today=None) -> list[str]:
    """URLs in the sitemap whose <lastmod> is within the last `days` days (inclusive)."""
    cutoff = (today or date.today()) - timedelta(days=days)
    urls = []
    for url in ET.parse(sitemap).getroot().iter(f"{NS}url"):
        loc = url.findtext(f"{NS}loc")
        lastmod = url.findtext(f"{NS}lastmod")
        if not loc or not lastmod:
            continue
        if date.fromisoformat(lastmod.strip()[:10]) >= cutoff:
            urls.append(loc.strip())
    return urls


@click.command()
@click.option("--dry-run", is_flag=True, help="Print the URLs that would be submitted; do not POST.")
def main(dry_run: bool) -> None:
    """Submit recently modified sitemap URLs to IndexNow. Always exits 0."""
    if not SITEMAP.is_file():
        print(f"indexnow: {SITEMAP} not found, run the build first; nothing submitted")
        return
    key = find_key()
    if not key:
        print(f"indexnow: no single 32-hex-character key file in {STATIC}/; nothing submitted")
        return
    urls = fresh_urls()
    if not urls:
        print(f"indexnow: no URLs modified in the last {FRESH_DAYS} days, nothing to submit")
        return
    if dry_run:
        print(f"indexnow: would submit {len(urls)} URL(s):")
        print("\n".join(urls))
        return
    payload = {
        "host": HOST,
        "key": key,
        "keyLocation": f"https://{HOST}/{key}.txt",
        "urlList": urls,
    }
    try:
        response = requests.post(ENDPOINT, json=payload, timeout=30)
    except requests.RequestException as e:
        print(f"indexnow: submission of {len(urls)} URL(s) failed: {e}")
        return
    print(f"indexnow: submitted {len(urls)} URL(s), HTTP {response.status_code}")
    if response.text.strip():
        print(response.text.strip())


if __name__ == "__main__":
    main()
