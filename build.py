#!/bin/python3

import json
import yaml
import glob
from markdown2 import markdown
from jinja2 import FileSystemLoader, Environment
from pathlib import Path
import shutil

build_dir = Path(".") / "build"
shutil.rmtree(build_dir, ignore_errors=True)
build_dir.mkdir(exist_ok=True)

env = Environment(loader=FileSystemLoader("html"))
template = env.get_template("template.html")
index_template = env.get_template("index.html")

## map page
with open(build_dir / "index.html", "w") as o:
    o.write(index_template.render())

## place pages
geojson_features = []

def rating_to_text(rating):
    if rating == 0:
        return "Bad"
    elif rating == 1:
        return "Inoffensive"
    elif rating == 2:
        return "Good"
    elif rating == 3:
        return "Phenomenal"
    else:
        raise ValueError("Bad rating")

for place_md in glob.glob("places/*.md"):
    slug = place_md[7:-3]
    print(slug)
    with open(place_md) as f:
        _, frontmatter, md = f.read().split("---", 2)
    meta = yaml.load(frontmatter, Loader=yaml.Loader)
    html = markdown(md.strip())
    rendered = template.render(
        **meta,
        taste_text=rating_to_text(meta["taste"]),
        value_text=rating_to_text(meta["value"]),
        content=html,
    )
    out_dir = build_dir / "places" / slug
    out_dir.mkdir(exist_ok=True, parents=True)
    with open(out_dir / "index.html", "w") as o:
        o.write(rendered)
    geojson_features.append({
      "type": "Feature",
      "geometry": {
        "type": "Point",
        "coordinates": [meta["lon"], meta["lat"]]
      },
      "properties": meta
    })

geojson = {
  "type": "FeatureCollection",
  "features": geojson_features
}

with open(build_dir / "places.geojson", "w") as o:
    o.write(json.dumps(geojson))
