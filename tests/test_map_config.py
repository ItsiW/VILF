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


def test_map_reserves_space_without_disabling_thumbnail_preloading():
    template = (Path(__file__).resolve().parents[1] / "html/map.html").read_text()
    assert 'flex: 0 0 auto;' in template
    assert 'line-height: 1.2;' in template
    assert 'flex: 1 1 0;' in template
    assert 'min-height: 0;' in template
    assert 'height: auto;' in template
    assert 'setTimeout(imagePreloader, 1000);' in template
    assert 'preload(...{{ thumbnails | tojson }});' in template
