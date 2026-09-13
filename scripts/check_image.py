"""Smoke-test the packaged admin, using a temporary DB and no cloud credentials.

Run inside the built image: python -m scripts.check_image
"""

import os
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from urllib.request import urlopen


def check_no_credentials(root):
    """Fail the image check if deployment credentials entered the build context."""
    assert not list(root.rglob("gha-creds-*.json")), "Deployment credentials found in image"
    assert not (root / ".env").exists(), "Local environment file found in image"
    assert not (root / "scripts/credentials.json").exists(), "Local credentials found in image"


def main():
    from jinja2 import Environment, FileSystemLoader
    from scripts.neighborhoods import suggest_area

    assert suggest_area(37.7633332, -122.4801045) == "Outer Sunset"

    root = Path(__file__).resolve().parent.parent
    check_no_credentials(root)
    templates = Environment(loader=FileSystemLoader(root / "app/templates"))
    for name in ["base.html", "places/list.html", "places/new.html", "places/edit.html",
                 "places/_form.html", "places/_table.html", "places/_candidates.html",
                 "photos/_panel.html", "publish/index.html", "publish/_pending.html",
                 "publish/history.html", "backups/index.html", "sync/index.html"]:
        templates.get_template(name)
    for name in ["admin.css", "htmx.min.js", "url-links.js", "review-editor.js", "favicon.svg"]:
        assert (root / "app/static" / name).is_file(), f"Missing asset: {name}"
    with TemporaryDirectory(prefix="vilf-image-check-") as tmp:
        env = dict(os.environ, DATABASE_URL=f"sqlite:///{tmp}/check.db",
                   VILF_MEDIA_STORAGE=f"{tmp}/media", VILF_SITE_STORAGE=f"{tmp}/site",
                   VILF_BACKUP_STORAGE="", VILF_ADMIN_EMAIL="", GOOGLE_CLOUD_PROJECT="",
                   GOOGLE_PLACES_API_KEY="", GOOGLE_MAPS_EMBED_API_KEY="",
                   VILF_URL_MAP="", VILF_INDEXNOW="0")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
            env=env, cwd=root,
        )
        base = f"http://127.0.0.1:{port}"
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError("Packaged admin failed to start")
                try:
                    with urlopen(base + "/healthz", timeout=1) as response:
                        assert response.status == 200
                    break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("Packaged admin startup timed out")
            for path in ["/places", "/places/new", "/publish", "/backups", "/sync",
                         "/static/admin.css", "/static/review-editor.js", "/static/favicon.svg"]:
                with urlopen(base + path, timeout=10) as response:
                    assert response.status == 200, path
                    assert response.read(), path
                print(f"Image smoke check passed: {path}", flush=True)
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    main()
