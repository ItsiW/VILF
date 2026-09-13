import pytest

from scripts.neighborhoods import boundaries, in_ring, suggest_area


@pytest.mark.parametrize("lat,lon,area", [
    (37.7633332, -122.4801045, "Outer Sunset"),  # Mini Potstickers
    (37.76, -122.435, "The Castro"),
    (37.78, -122.41, "Soma"),
    (37.76, -122.415, "The Mission"),
    (37.770457, -122.409002, "Soma"),  # western Showplace Square
    (37.766208, -122.404600, "Mission Bay"),
    (37.727609, -122.423201, "Excelsior"),  # western University Mound
    (37.724534, -122.418893, "Portola"),
    (37.749798, -122.449143, "Twin Peaks"),  # western Upper Market
    (37.748018, -122.443408, "Noe Valley"),
    (37.8061, -122.2683, None),  # Oakland: don't guess an SF neighborhood
    (37.8, -122.49, None),  # ocean, within the coarse bounding box
    (None, None, None), ("bad", 0, None), (float("nan"), -122.4, None),
    (37.76, float("inf"), None),
])
def test_suggestions(lat, lon, area):
    assert suggest_area(lat, lon) == area


def test_complete_dataset_is_packaged():
    assert len(boundaries()) == 117


@pytest.mark.parametrize("lat,lon,expected", [
    (37.7765818, -122.4417657, "Nopa"),  # Bob's
    (37.7781752, -122.4386952, "Nopa"),  # Brenda's
    (37.7746527, -122.4379523, "Nopa"),  # Club Waziema
    (37.7768417, -122.4377418, "Nopa"),  # Indian Saffron, east frontage
    (37.7740, -122.4520, "Nopa"),  # west extension
    (37.7764, -122.4346, "Alamo Square"),
])
def test_nopa_boundary(lat, lon, expected):
    assert suggest_area(lat, lon) == expected


def test_nopa_does_not_include_park_or_lone_mountain():
    assert suggest_area(37.7724, -122.4480) != "Nopa"
    assert suggest_area(37.7780, -122.4500) != "Nopa"


@pytest.mark.parametrize("source,expected", [
    ("Central Waterfront", "Dogpatch"), ("Lower Nob Hill", "Nob Hill"),
    ("Union Street", "Cow Hollow"), ("Downtown / Union Square", "Union Square"),
    ("Laurel Heights / Jordan Park", "Laurel Heights"), ("Mission", "The Mission"),
    ("Mission Dolores", "Mission Dolores"), ("Lower Pacific Heights", "Pac Heights"),
    ("Pacific Heights", "Pac Heights"),
    ("Eureka Valley", "The Castro"), ("Castro", "The Castro"),
    ("Northern Waterfront", "Embarcadero"),
    ("Aquatic Park / Ft. Mason", "Fort Mason"),
    ("Lincoln Park / Ft. Miley", "Outer Richmond"),
    ("Mint Hill", "Hayes Valley"), ("Apparel City", "Bayview"),
    ("Produce Market", "Bayview"), ("Peralta Heights", "Bernal Heights"),
])
def test_preferred_names(monkeypatch, source, expected):
    from scripts import neighborhoods
    monkeypatch.setattr(neighborhoods, "boundaries", lambda: [{
        "properties": {"name": source}, "geometry": {"coordinates": [[[
            [-122.5, 37.7], [-122.4, 37.7], [-122.4, 37.8], [-122.5, 37.8], [-122.5, 37.7],
        ]]]}}])
    assert suggest_area(37.75, -122.45) == expected


def test_ring_edges():
    ring = [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]
    assert in_ring(1, 1, ring)
    assert in_ring(0, 1, ring)
    assert in_ring(0, 0, ring)
    assert not in_ring(3, 1, ring)


def test_holes_and_multipolygons(monkeypatch):
    from scripts import neighborhoods
    exterior = [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]
    hole = [[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]]
    def shifted(ring):
        return [[-122.5 + x * .01, 37.7 + y * .01] for x, y in ring]
    second = [[5, 0], [6, 0], [6, 1], [5, 1], [5, 0]]
    monkeypatch.setattr(neighborhoods, "boundaries", lambda: [{
        "properties": {"name": "Test"}, "geometry": {
            "coordinates": [[shifted(exterior), shifted(hole)], [shifted(second)]]}}])
    assert suggest_area(37.705, -122.495) == "Test"
    assert suggest_area(37.72, -122.48) is None
    assert suggest_area(37.705, -122.445) == "Test"
