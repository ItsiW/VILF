from pathlib import Path


def test_map_uses_account_free_tiles_and_pinned_module():
    template = (Path(__file__).resolve().parents[1] / "html/map.html").read_text()
    assert 'https://tiles.openfreemap.org/styles/liberty' in template
    assert 'mapbox://' not in template and 'accessToken' not in template
    assert 'maplibre-gl@6.9.0/dist/maplibre-gl.mjs' in template
    assert 'maplibre-gl@6.9.0/dist/maplibre-gl.css' in template
    assert '<script type="module">' in template
    assert '"Noto Sans Bold"' in template
    assert '"minzoom": 14' in template
    assert 'const feature = event.features[0]' in template
    assert '{{ thumbnails | tojson }}' in template
    assert 'preload.arguments' not in template
