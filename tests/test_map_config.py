from pathlib import Path


def test_map_uses_account_free_tiles_and_pinned_module():
    template = (Path(__file__).resolve().parents[1] / "html/map.html").read_text()
    assert 'https://tiles.openfreemap.org/styles/liberty' in template
    assert 'mapbox://' not in template and 'accessToken' not in template
    assert 'maplibre-gl@6.9.0/dist/maplibre-gl.mjs' in template
    assert 'vendor/maplibre-gl-6.9.0.css' in template
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


def test_map_header_uses_a_narrow_serif_fallback_until_fonts_load():
    template = (Path(__file__).resolve().parents[1] / "html/map.html").read_text()
    # The shared Comic Sans fallback wraps the desktop navigation on Linux,
    # then lifts the entire map when Emilys Candy finishes loading.
    rule = template.split('.header .vilf, .header .tm {', 1)[1].split('}', 1)[0]
    assert "font-family: 'Emilys Candy', 'Times New Roman', Times, serif;" in rule
    assert 'Comic Sans' not in rule
    assert '@media (max-width: 1349px)' in template
    assert 'flex-basis: 100%;' in template
    # Legends follow the map below either header layout, not viewport offsets.
    assert 'position: relative;' in template.split('.content-wrapper {', 1)[1].split('}', 1)[0]
    assert 'top: 0.5rem;' in template
    assert 'top: 5.5rem;' in template
