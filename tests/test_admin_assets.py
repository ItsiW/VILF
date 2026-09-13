from app import main


def test_asset_url_changes_when_contents_change(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "APP_DIR", tmp_path)
    static = tmp_path / "static"
    static.mkdir()
    css = static / "admin.css"
    css.write_text("textarea { font-weight: 600; }")
    before = main.static_asset_url("admin.css")
    assert before.startswith("/static/admin.css?v=")
    assert before == main.static_asset_url("admin.css")
    css.write_text("textarea { font-weight: 400; }")
    assert before != main.static_asset_url("admin.css")


def test_admin_favicon_is_served_and_linked(tmp_path):
    from fastapi.testclient import TestClient
    from scripts.config import Settings

    client = TestClient(main.create_app(Settings(
        database_url=f"sqlite:///{tmp_path}/test.db",
        media_storage=str(tmp_path / "media"), site_storage=str(tmp_path / "site"))))
    page = client.get("/places").text
    assert f'href="{main.static_asset_url("favicon.svg")}"' in page
    assert 'rel="icon" type="image/svg+xml"' in page
    response = client.get(main.static_asset_url("favicon.svg"))
    assert response.status_code == 200
    assert "image/svg+xml" in response.headers["content-type"]
    assert "VILF admin" in response.text
