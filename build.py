#!/bin/python3

import glob
import json
import shutil
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader
from markdown2 import markdown

print("Starting build of tgtg...")

build_dir = Path(".") / "build"
shutil.rmtree(build_dir, ignore_errors=True)
build_dir.mkdir(exist_ok=True)

env = Environment(loader=FileSystemLoader("html"))
place_template = env.get_template("place.html")

## map page
with open(build_dir / "index.html", "w") as o:
    o.write(
        env.get_template("index.html").render(
            title="The Good Taste Guide",
            description="Find tasty vegan food around New York City!",
        )
    )

## error page
with open(build_dir / "error.html", "w") as o:
    o.write(
        env.get_template("error.html").render(
            title="The Good Taste Guide",
            description="An error occured.",
        )
    )

## place pages
places = []


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


def format_title(meta):
    return f"{meta['name']} — Tasty vegan food in {meta['area']} — The Good Taste Guide"


def format_description(meta):
    return f"Read our review on {meta['name']} at {meta['address']} in {meta['area']}, and more tasty vegan food in New York City from The Good Taste Guide!"


for place_md in glob.glob("places/*.md"):
    slug = place_md[7:-3]
    relative_url = f"/places/{slug}/"
    with open(place_md) as f:
        _, frontmatter, md = f.read().split("---", 2)
    meta = yaml.load(frontmatter, Loader=yaml.Loader)
    meta["url"] = relative_url
    html = markdown(md.strip())
    rendered = place_template.render(
        **meta,
        taste_text=rating_to_text(meta["taste"]),
        value_text=rating_to_text(meta["value"]),
        title=format_title(meta),
        description=format_description(meta),
        content=html,
    )
    out_dir = build_dir / "places" / slug
    out_dir.mkdir(exist_ok=True, parents=True)
    with open(out_dir / "index.html", "w") as o:
        o.write(rendered)
    places.append(meta)

geojson = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [place["lon"], place["lat"]]},
            "properties": place,
        }
        for place in places
    ],
}

with open(build_dir / "places.geojson", "w") as o:
    o.write(json.dumps(geojson))

## list page
list_dir = build_dir / "list"
list_dir.mkdir(exist_ok=True, parents=True)
with open(list_dir / "index.html", "w") as o:
    o.write(
        env.get_template("list.html").render(
            title="The Good Taste Guide",
            description="Find tasty vegan food around New York City!",
            places=places,
        )
    )

print("Done building tgtg.")
