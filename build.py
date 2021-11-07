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
        env.get_template("map.html").render(
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

## about page
about_dir = build_dir / "about"
about_dir.mkdir(exist_ok=True, parents=True)
with open(about_dir / "index.html", "w") as o:
    o.write(
        env.get_template("about.html").render(
            title="About — The Good Taste Guide",
            description="Want to know how The Good Taste Guide got started? Find out here!",
        )
    )

## place pages
places = []


rating_labels = ["Bad", "Inoffensive", "Good", "Phenomenal"]
rating_colors = ["#ef422b", "#efa72b", "#32af2d", "#2b9aef"]


def rating_to_formatting(rating):
    return rating_labels[rating], rating_colors[rating]


def rating_html(rating):
    return " ".join(
        [
            f'<span style="color: {color if rating == ix else "#b1b1b1"}" aria-hidden="{"true" if rating == ix else "false"}">{label}</span>'
            for ix, (label, color) in enumerate(zip(rating_labels, rating_colors))
        ]
    )


def format_title(meta):
    return f'{meta["name"]} — Tasty vegan food in {meta["area"]} — The Good Taste Guide'


def format_description(meta):
    return f'Read our review on {meta["name"]} at {meta["address"]} in {meta["area"]}, and more tasty vegan {meta["cuisine"]} food in New York City from The Good Taste Guide!'


def format_phone_number(meta):
    if "phone" not in meta or not meta["phone"]:
        return None
    numstring = str(meta["phone"])
    if numstring[0] == "1":
        numstring = numstring[1:]
    return f"{numstring[0:3]}-{numstring[3:6]}-{numstring[6:10]}"


def format_geodata(meta):
    return f'{meta["lat"]},{meta["lon"]}'


for place_md in glob.glob("places/*.md"):
    slug = place_md[7:-3]
    relative_url = f"/places/{slug}/"
    with open(place_md) as f:
        _, frontmatter, md = f.read().split("---", 2)
    meta = yaml.load(frontmatter, Loader=yaml.Loader)
    meta["url"] = relative_url
    meta["slug"] = slug
    meta["geodata"] = format_geodata(meta)
    meta["phone_display"] = format_phone_number(meta)
    meta["taste_label"], meta["taste_color"] = rating_to_formatting(meta["taste"])
    meta["value_label"], meta["value_color"] = rating_to_formatting(meta["value"])
    html = markdown(md.strip())
    rendered = place_template.render(
        **meta,
        title=format_title(meta),
        description=format_description(meta),
        taste_html=rating_html(meta["taste"]),
        value_html=rating_html(meta["value"]),
        content=html,
    )
    out_dir = build_dir / "places" / slug
    out_dir.mkdir(exist_ok=True, parents=True)
    with open(out_dir / "index.html", "w") as o:
        o.write(rendered)
    places.append(meta)

# sort by taste desc, then value desc, then alphabetical by name
places.sort(key=lambda item: (-item["taste"], -item["value"], item["slug"]))

geojson = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [place["lon"], place["lat"]]},
            "properties": place,
        }
        for place in reversed(places)
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

with open(build_dir / "robots.txt", "w") as o:
    o.write("User-agent: *\nDisallow:\n")

print("Done building tgtg.")
