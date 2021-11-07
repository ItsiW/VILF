#!/bin/python3

import glob
import json
import shutil
from datetime import date
from pathlib import Path
import re

import yaml
from jinja2 import Environment, FileSystemLoader
from markdown2 import markdown
from mdplain import plain

SITE_URL = "https://thegoodtaste.guide"

print("Starting build of tgtg...")

env = Environment(loader=FileSystemLoader("html"))
env.globals["SITE_URL"] = SITE_URL

build_dir = Path(".") / "build"
shutil.rmtree(build_dir, ignore_errors=True)
shutil.copytree(Path("static/"), build_dir)

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
place_template = env.get_template("place.html")
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


boolean_labels = ["Nah", "Yeah"]
boolean_colors = ["#ef422b", "#2b9aef"]


def boolean_to_formatting(boolean):
    return boolean_labels[boolean], boolean_colors[boolean]


def boolean_html(boolean):
    return " ".join(
        [
            f'<span style="color: {color if boolean == ix else "#b1b1b1"}" aria-hidden="{"true" if boolean == ix else "false"}">{label}</span>'
            for ix, (label, color) in enumerate(zip(boolean_labels, boolean_colors))
        ]
    )


def format_title(meta):
    return f'{meta["name"]} — Tasty vegan food in {meta["area"]} — The Good Taste Guide'


def format_description(meta):
    return f'Read our review on {meta["name"]} at {meta["address"]} in {meta["area"]}, and more tasty vegan {meta["cuisine"]} food in New York City from The Good Taste Guide!'


def format_phone_number(meta):
    if not "phone" in meta:
        return
    number = meta["phone"]
    assert len(number) == 12
    assert number[:2] == "+1"
    return f"({number[2:5]}) {number[5:8]}-{number[8:12]}"


assert format_phone_number({"phone": "+12345678987"}) == "(234) 567-8987"


def format_geodata(meta):
    return f'{meta["lat"]},{meta["lon"]}'


def suffix(d):
    return "th" if 11 <= d <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(d % 10, "th")


def custom_strftime(format_, t):
    return t.strftime(format_).replace("{S}", str(t.day) + suffix(t.day))


def format_visited(visited):
    return custom_strftime("{S} %B %Y", date.fromisoformat(visited))

def format_blurb(md):
    return " ".join(plain(re.sub(r"\s+", " ", md.strip())).split(" ")[:50]) + "..."

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
    meta["visited_display"] = format_visited(meta["visited"])
    meta["taste_label"], meta["taste_color"] = rating_to_formatting(meta["taste"])
    meta["value_label"], meta["value_color"] = rating_to_formatting(meta["value"])
    meta["drinks_label"], meta["drinks_color"] = boolean_to_formatting(meta["drinks"])
    html = markdown(md.strip())
    meta["blurb"] = format_blurb(md)
    rendered = place_template.render(
        **meta,
        title=format_title(meta),
        description=format_description(meta),
        taste_html=rating_html(meta["taste"]),
        value_html=rating_html(meta["value"]),
        drinks_html=boolean_html(meta["drinks"]),
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

## best page
best_dir = build_dir / "best"
best_dir.mkdir(exist_ok=True, parents=True)
with open(best_dir / "index.html", "w") as o:
    o.write(
        env.get_template("best.html").render(
            title="The Good Taste Guide",
            description="Find tasty vegan food around New York City!",
            places=places,
        )
    )

## latest page
latest_places = places.copy()
latest_places.sort(key=lambda item: (item["slug"]), reverse=False)
latest_places.sort(key=lambda item: (item["visited"]), reverse=True)


latest_dir = build_dir / "latest"
latest_dir.mkdir(exist_ok=True, parents=True)
with open(latest_dir / "index.html", "w") as o:
    o.write(
        env.get_template("latest.html").render(
            title="Latest Reviews from The Good Taste Guide",
            description="Find tasty vegan food around New York City!",
            places=latest_places,
        )
    )

with open(build_dir / "robots.txt", "w") as o:
    o.write("User-agent: *\nDisallow:\n")

print("Done building tgtg.")
