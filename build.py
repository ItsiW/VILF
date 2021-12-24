#!/bin/python3

import glob
import json
import os
import re
import shutil
from datetime import date
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader
from markdown2 import markdown
from mdplain import plain
from PIL import Image

SITE_URL = "https://thegoodtaste.guide"

print("Starting build of tgtg...")

env = Environment(loader=FileSystemLoader("html"))
env.globals["SITE_URL"] = SITE_URL

build_dir = Path(".") / "build"
shutil.rmtree(build_dir, ignore_errors=True)

# scale, crop and store standardised images
food_image_target_size = (1920, 1080)
food_thumb_target_size = (426, 240)
jpg_quality = 75

shutil.rmtree("static/img", ignore_errors=True)
os.makedirs("static/img/food")
os.makedirs("static/img/thumb")
os.makedirs("static/img/memes")

for raw_jpg in glob.glob("raw/food/*.jpg"):
    static_fp = Path(f"img/food/{raw_jpg[9:-4]}.jpg")
    thumb_fp = Path(f"img/thumb/{raw_jpg[9:-4]}.jpg")
    with Image.open(raw_jpg) as im:
        assert im.size[0] / im.size[1] <= 16 / 9
        im = im.resize(
            (
                food_image_target_size[0],
                int(food_image_target_size[0] * im.size[1] / im.size[0]),
            )
        )
        pixels_to_crop = int((im.size[1] - food_image_target_size[1]) / 2)
        (left, upper, right, lower) = (
            0,
            pixels_to_crop,
            food_image_target_size[0],
            food_image_target_size[1] + pixels_to_crop,
        )
        im_cropped = im.crop((left, upper, right, lower))
        im_cropped.save(
            fp=Path("static/") / static_fp, format="JPEG", quality=jpg_quality
        )

        # thumbnails for images on map
        im_thumb = im_cropped.resize(
            (food_thumb_target_size[0], food_thumb_target_size[1])
        )
        im_thumb.save(fp=Path("static/") / thumb_fp, format="JPEG", quality=jpg_quality)

for meme_id, raw_meme in enumerate(glob.glob("raw/memes/*")):
    fp = Path(f"img/memes/{meme_id}.jpg")
    with Image.open(raw_meme) as im:
        im.save(fp=Path("static/") / fp, format="JPEG", quality=jpg_quality)
n_memes = meme_id + 1

shutil.copytree(Path("static/"), build_dir)

sitemap = []

## map page
with open(build_dir / "index.html", "w") as o:
    o.write(
        env.get_template("map.html").render(
            title="The Good Taste Guide",
            description="Find tasty vegan food around New York City!",
        )
    )
sitemap.append(
    {
        "url": f"{SITE_URL}/",
    }
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
with open("./about.md") as f:
    _, frontmatter, md = f.read().split("---", 2)
meta = yaml.load(frontmatter, Loader=yaml.Loader)
html = markdown(md.strip())
with open(about_dir / "index.html", "w") as o:
    o.write(
        env.get_template("about.html").render(
            **meta,
            content=html,
        )
    )
sitemap.append(
    {
        "url": f"{SITE_URL}/about/",
    }
)

## place pages
place_template = env.get_template("place.html")
places = []


taste_labels = ["DNR", "SGFI", "Good", "Phenomenal"]
value_labels = ["Bad", "Fine", "Good", "Phenomenal"]
rating_colors = ["#ef422b", "#efa72b", "#32af2d", "#2b9aef"]
faded_color = "#cecece"


def rating_to_formatting(rating, rating_labels):
    return rating_labels[rating], rating_colors[rating]


def rating_html(rating, rating_labels):
    return "&nbsp;".join(
        [
            f'<span style="color: {color if rating == ix else faded_color}" aria-hidden="{"false" if rating == ix else "true"}">{label}</span>'
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
            f'<span style="color: {color if boolean == ix else faded_color}" aria-hidden="{"false" if boolean == ix else "true"}">{label}</span>'
            for ix, (label, color) in enumerate(zip(boolean_labels, boolean_colors))
        ]
    )


def format_title(meta):
    return f'{meta["name"]} — Tasty vegan food in {meta["area"]}, New York — The Good Taste Guide'


def format_description(meta):
    return f'Read our review on {meta["name"]} at {meta["address"]} in {meta["area"]}, and more tasty vegan {meta["cuisine"]} food in New York City from The Good Taste Guide!'


def format_phone_number(meta):
    if meta["phone"] is None:
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
    return custom_strftime("{S} %B %Y", visited)


def format_blurb(md):
    return " ".join(plain(re.sub(r"\s+", " ", md.strip())).split(" ")[:50]) + "..."


def get_fp_food_image(slug):
    static_fp = f"/img/food/{slug}.jpg"
    return static_fp if Path(f"static{static_fp}").exists() else None


def get_fp_food_thumb(slug):
    static_fp = f"/img/thumb/{slug}.jpg"
    return static_fp if Path(f"static{static_fp}").exists() else None


for place_md in glob.glob("places/*.md"):
    slug = place_md[7:-3]
    assert re.match(r"^[0-9a-z-]+$", slug), "Bad filename for " + place_md
    relative_url = f"/places/{slug}/"
    with open(place_md) as f:
        _, frontmatter, md = f.read().split("---", 2)
    meta = yaml.load(frontmatter, Loader=yaml.Loader)
    meta["url"] = relative_url
    meta["slug"] = slug
    meta["geodata"] = format_geodata(meta)
    meta["phone_display"] = format_phone_number(meta)
    visited = date.fromisoformat(meta["visited"])
    meta["visited_display"] = format_visited(visited)
    meta["review_age"] = (date.today() - visited).days
    meta["taste_label"], meta["taste_color"] = rating_to_formatting(
        meta["taste"], taste_labels
    )
    meta["value_label"], meta["value_color"] = rating_to_formatting(
        meta["value"], value_labels
    )
    meta["drinks_label"], meta["drinks_color"] = boolean_to_formatting(meta["drinks"])
    html = markdown(md.strip())
    meta["blurb"] = format_blurb(md)
    meta["food_image_path"] = get_fp_food_image(slug)
    meta["food_thumb_path"] = get_fp_food_thumb(slug)
    rendered = place_template.render(
        **meta,
        title=format_title(meta),
        description=format_description(meta),
        taste_html=rating_html(meta["taste"], taste_labels),
        value_html=rating_html(meta["value"], value_labels),
        drinks_html=boolean_html(meta["drinks"]),
        content=html,
        n_memes=n_memes,
    )
    out_dir = build_dir / "places" / slug
    out_dir.mkdir(exist_ok=True, parents=True)
    with open(out_dir / "index.html", "w") as o:
        o.write(rendered)
    places.append(meta)

    sitemap.append(
        {
            "url": f"{SITE_URL}{relative_url}",
            "lastmod": visited,
        }
    )

unique_fields = ["name", "geodata", "menu", "phone", "blurb"]

for field in unique_fields:
    field_list = [place[field] for place in places if place[field] is not None]
    assert len(set(field_list)) == len(field_list), f"Reused {field} field"

geojson_keys = [
    "name",
    "cuisine",
    "url",
    "taste_color",
    "taste_label",
    "value_color",
    "value_label",
    "food_thumb_path",
]

geojson = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [place["lon"], place["lat"]]},
            "properties": {
                key: value for key, value in place.items() if key in geojson_keys
            },
        }
        # sort reverse of by taste desc, then value desc, then alphabetical by name
        for place in sorted(
            places,
            key=lambda item: (-item["taste"], -item["value"], item["slug"]),
            reverse=True,
        )
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
            # sort by taste desc, then value desc, then alphabetical by name
            places=sorted(
                places, key=lambda item: (-item["taste"], -item["value"], item["slug"])
            ),
        )
    )
sitemap.insert(
    2,
    {
        "url": f"{SITE_URL}/best/",
        "changefreq": "daily",
    },
)


## latest page
latest_dir = build_dir / "latest"
latest_dir.mkdir(exist_ok=True, parents=True)
with open(latest_dir / "index.html", "w") as o:
    o.write(
        env.get_template("latest.html").render(
            title="Latest Reviews from The Good Taste Guide",
            description="Find tasty vegan food around New York City!",
            # sort by age then standard
            places=sorted(
                places,
                key=lambda item: (
                    item["review_age"],
                    -item["taste"],
                    -item["value"],
                    item["slug"],
                ),
            ),
        )
    )
sitemap.insert(
    2,
    {
        "url": f"{SITE_URL}/latest/",
        "changefreq": "daily",
    },
)

with open(build_dir / "sitemap.xml", "w") as o:
    o.write(
        env.get_template("sitemap.xml").render(
            urls=[
                (
                    item.get("url"),
                    item.get("lastmod", date.today()),
                    item.get("changefreq"),
                )
                for item in sitemap
            ]
        )
    )

with open(build_dir / "robots.txt", "w") as o:
    o.write("User-agent: *\nDisallow:\n")

print("Done building tgtg.")
