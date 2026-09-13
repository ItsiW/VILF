# SF neighborhood boundaries

`sf-neighborhoods.geojson` is a bundled copy of DataSF's **SF Find Neighborhoods**,
downloaded September 12, 2026 PT. Source: City and County of San Francisco,
Mayor's Office of Neighborhood Services (boundaries defined in 2006).

- Dataset: https://data.sf.gov/Geographic-Locations-and-Boundaries/SF-Find-Neighborhoods/gfpk-269f
- GeoJSON: https://data.sf.gov/resource/gfpk-269f.geojson?$limit=1000
- License: Public Domain U.S. Government (DataSF dataset listing).

All 117 MultiPolygon geometries are retained without simplification; only the
name property is kept. These are general neighborhood locations, not definitive
boundaries. The admin uses them only to prefill an editable field for new Google
selections. Nothing is fetched at runtime or applied to existing records.

`scripts/neighborhoods.py` maps source labels to the owner's preferred names:
Mission → The Mission; Central Waterfront → Dogpatch; Lower Nob Hill → Nob Hill;
Union Street → Cow Hollow; Downtown / Union Square → Union Square;
Laurel Heights / Jordan Park → Laurel Heights; both Pacific Heights and Lower
Pacific Heights → Pac Heights. Mission Dolores stays separate. Existing spelling
aliases for The Castro, Haight-Ashbury and Soma remain in place.
Eureka Valley also becomes The Castro; Northern Waterfront becomes Embarcadero;
Aquatic Park / Ft. Mason becomes Fort Mason; Lincoln Park / Ft. Miley becomes
Outer Richmond. Mint Hill becomes Hayes Valley; Apparel City and Produce Market
become Bayview; Peralta Heights becomes Bernal Heights.
These mappings rename suggestions without changing source geometry or saved rows.
Other names are preserved; do not merge more districts without agreement.
Points on shared boundaries use
alphabetical feature order. Outside coverage, leave the field unfilled.

## Location-specific splits

`sf-area-splits.geojson` contains three unchanged geometries from DataSF's
Analysis Neighborhoods dataset (`j2bu-swwd`), retrieved September 12, 2026 PT:
https://data.sf.gov/resource/j2bu-swwd.geojson?$limit=1000

Within Upper Market, points in the broader Noe Valley polygon become Noe Valley;
the remainder becomes Twin Peaks. Within University Mound, points in Excelsior
become Excelsior; the remainder becomes Portola. Within Showplace Square, points
in Mission Bay become Mission Bay; the remainder becomes Soma. These are agreed
editorial simplifications, not exact equivalences between the two datasets.

## Nopa override

Use NOPNA's core: Fell to Turk, Divisadero to Masonic, plus the west extension
between Fell and Fulton, Masonic and Stanyan. This excludes the Panhandle park,
Alamo Square park, and Lone Mountain. Allow approximately 50 m of east-side
Divisadero frontage to include businesses on both sides. The override takes
precedence over the detailed dataset; it is an editorial boundary, not an
official designation. Corners use DataSF Street Intersections (`gmfx-8h6i`),
retrieved September 12, 2026 PT, joined by straight segments.

- NOPNA core: https://nopna.squarespace.com/20162marchapril
- West extension testimony: https://media.api.sf.gov/documents/April_18_through_April_24_2022.pdf
- Intersections: https://data.sf.gov/resource/gmfx-8h6i.json
