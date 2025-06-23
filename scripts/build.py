#!/bin/python3

import json
import os
import re
import shutil
from datetime import date
from pathlib import Path

import click
import yaml
from jinja2 import Environment, FileSystemLoader
from markdown2 import markdown
from mdplain import plain
from PIL import Image
from tqdm import tqdm

SITE_URL = "https://vilf.org"


@click.command()
def build_vilf() -> None:
    """Build VILF locally."""
    print("Starting build of scripts...")

    env = Environment(loader=FileSystemLoader("html"))
    env.globals["SITE_URL"] = SITE_URL

    build_dir = Path("./build")
    shutil.rmtree(build_dir, ignore_errors=True)

    # scale, crop and store standardised images  
    food_image_target_size = (1200, 675)  # Balanced: good quality + reasonable file size
    food_thumb_target_size = (426, 240)
    jpg_quality = 82  # Higher quality for better visual appeal

    for img_type in ["food", "thumb"]:
        path = Path(f"static/img/{img_type}")
        if not os.path.exists(path):
            os.makedirs(path)

    for raw_jpg in tqdm(
        list(Path("raw/food").glob("*.jpg")), desc="processing food images"
    ):
        file_name = raw_jpg.parts[-1]
        file_stem = raw_jpg.stem
        static_fp_jpg = Path("img/food") / file_name
        static_fp_webp = Path("img/food") / f"{file_stem}.webp"
        thumb_fp_jpg = Path("img/thumb") / file_name
        thumb_fp_webp = Path("img/thumb") / f"{file_stem}.webp"
        
        # Check if all formats exist
        files_exist = all([
            (Path("static") / static_fp_jpg).exists(),
            (Path("static") / static_fp_webp).exists(),
            (Path("static") / thumb_fp_jpg).exists(),
            (Path("static") / thumb_fp_webp).exists()
        ])
        
        if not files_exist:
            with Image.open(raw_jpg) as im:
                assert im.size[0] / im.size[1] <= 16 / 9
                im = im.convert("RGB")
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
                
                # Save full-size images in both formats
                im_cropped.save(
                    fp=Path("static") / static_fp_jpg, format="JPEG", quality=jpg_quality
                )
                im_cropped.save(
                    fp=Path("static") / static_fp_webp, format="WEBP", quality=jpg_quality
                )

                # thumbnails for images on map
                im_thumb = im_cropped.resize(
                    (food_thumb_target_size[0], food_thumb_target_size[1])
                )
                im_thumb.save(
                    fp=Path("static") / thumb_fp_jpg, format="JPEG", quality=jpg_quality
                )
                im_thumb.save(
                    fp=Path("static") / thumb_fp_webp, format="WEBP", quality=jpg_quality
                )

    shutil.copytree(Path("static"), build_dir)

    sitemap = []

    # map page
    with open(build_dir / "index.html", "w") as o:
        o.write(
            env.get_template("map.html").render(
                title="Vegans In Love with Food",
                description="Find tasty vegan food in the San Francisco Bay Area with V.I.L.F!",
                thumbnails=[
                    str(Path(*file.parts[1:]))
                    for file in Path("static/img/thumb").iterdir()
                ],
            )
        )
    sitemap.append(
        {
            "url": f"{SITE_URL}/",
        }
    )

    # error page
    with open(build_dir / "error.html", "w") as o:
        o.write(
            env.get_template("error.html").render(
                title="Vegans In Love with Food",
                description="An error occured.",
            )
        )

    # about page
    about_dir = build_dir / "about"
    about_dir.mkdir(exist_ok=True, parents=True)
    with open(Path("about.md")) as f:
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

    # place pages
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
        return f'{meta["name"]} — Tasty vegan food in {meta["area"]}, in the San Francisco Bay Area — Vegans In Love with Food'

    def format_description(meta):
        return f'Read our review on {meta["name"]} at {meta["address"]} in {meta["area"]}, and more tasty vegan {meta["cuisine"]} food in the San Francisco Bay Area from V.I.L.F!'

    def format_description_with_dishes(meta, md):
        """Generate enhanced meta description with specific dishes mentioned"""
        # Extract dishes marked with ** from review text
        dishes = re.findall(r'\*\*(.*?)\*\*', md)
        
        if dishes:
            dishes_text = ", ".join(dishes[:2])  # Max 2 dishes for meta description
            return f'Read our review on {meta["name"]} featuring {dishes_text} at {meta["address"]} in {meta["area"]}, and more tasty vegan {meta["cuisine"]} food in the San Francisco Bay Area from V.I.L.F!'
        else:
            return f'Read our review on {meta["name"]} at {meta["address"]} in {meta["area"]}, and more tasty vegan {meta["cuisine"]} food in the San Francisco Bay Area from V.I.L.F!'

    def format_phone_number(meta):
        if meta["phone"] is None:
            return
        number = meta["phone"]
        assert len(number) == 12, meta["slug"]
        assert number[:2] == "+1", meta["slug"]
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

    def format_alt_text(meta, md):
        """Generate enhanced alt text with specific dishes mentioned"""
        base_alt = f"Vegan {meta['cuisine']} food at {meta['name']} in {meta['area']}, San Francisco Bay Area"
        
        # Extract dishes marked with ** from review text
        dishes = re.findall(r'\*\*(.*?)\*\*', md)
        if dishes:
            dishes_text = ", ".join(dishes[:3])  # Max 3 dishes
            return f"{base_alt} featuring {dishes_text}"
        return base_alt

    def get_fp_food_image(slug):
        # Prefer WebP if available, fallback to JPEG
        webp_fp = Path(f"img/food/{slug}.webp")
        jpg_fp = Path(f"img/food/{slug}.jpg")
        
        if (Path("static") / webp_fp).exists():
            return str(Path(f"/{webp_fp}"))
        elif (Path("static") / jpg_fp).exists():
            return str(Path(f"/{jpg_fp}"))
        else:
            return None

    def get_fp_food_thumb(slug):
        # Prefer WebP if available, fallback to JPEG
        webp_fp = Path(f"img/thumb/{slug}.webp")
        jpg_fp = Path(f"img/thumb/{slug}.jpg")
        
        if (Path("static") / webp_fp).exists():
            return str(Path(f"/{webp_fp}"))
        elif (Path("static") / jpg_fp).exists():
            return str(Path(f"/{jpg_fp}"))
        else:
            return None

    for place_md in Path("places").glob("*.md"):
        try:
            slug = place_md.parts[-1][:-3]
            assert re.match(r"^[0-9a-z-]+$", slug), "Bad filename for " + str(place_md)
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
            if meta["taste"] >= 1:
                assert "**" in md, f"highlight food in {meta['slug']}"
            meta["taste_label"], meta["taste_color"] = rating_to_formatting(
                meta["taste"], taste_labels
            )
            meta["value_label"], meta["value_color"] = rating_to_formatting(
                meta["value"], value_labels
            )
            meta["drinks_label"], meta["drinks_color"] = boolean_to_formatting(
                meta["drinks"]
            )
            html = markdown(md.strip())
            meta["blurb"] = format_blurb(md)
            meta["alt_text"] = format_alt_text(meta, md)
            meta["food_image_path"] = get_fp_food_image(slug)
            meta["food_thumb_path"] = get_fp_food_thumb(slug)
            rendered = place_template.render(
                **meta,
                title=format_title(meta),
                description=format_description_with_dishes(meta, md),
                taste_html=rating_html(meta["taste"], taste_labels),
                value_html=rating_html(meta["value"], value_labels),
                drinks_html=boolean_html(meta["drinks"]),
                content=html,
            )
            out_dir = build_dir / "places" / slug
            out_dir.mkdir(exist_ok=True, parents=True)
            with open(out_dir / "index.html", "w") as o:
                o.write(rendered)
            places.append(meta)
            sitemap.append(
                {
                    "url": f"{SITE_URL}{relative_url}",
                    "lastmod": max(visited, date(2025, 2, 15)),
                }
            )
        except Exception as e:
            print(place_md.name, e)

    unique_fields = ["name", "lat", "lon", "menu", "phone", "blurb"]

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
        "food_image_path",
    ]

    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [place["lon"], place["lat"]],
                },
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

    # best page
    best_dir = build_dir / "best"
    best_dir.mkdir(exist_ok=True, parents=True)
    with open(best_dir / "index.html", "w") as o:
        o.write(
            env.get_template("best.html").render(
                title="Vegans In Love with Food",
                description="Find tasty vegan food around the San Francisco Bay Area with V.I.L.F!",
                # sort by taste desc, then value desc, then alphabetical by name
                places=sorted(
                    places,
                    key=lambda item: (-item["taste"], -item["value"], item["slug"]),
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

    # latest page
    latest_dir = build_dir / "latest"
    latest_dir.mkdir(exist_ok=True, parents=True)
    with open(latest_dir / "index.html", "w") as o:
        o.write(
            env.get_template("latest.html").render(
                title="Latest Reviews from Vegans In Love with Food",
                description="Find tasty vegan food around the San Francisco Bay Area!",
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

    cuisine_names = sorted(set([place["cuisine"] for place in places]))

    cuisines_dir = build_dir / "cuisines"
    cuisines_dir.mkdir(exist_ok=True, parents=True)
    with open(cuisines_dir / "index.html", "w") as o:
        o.write(
            env.get_template("cuisine-list.html").render(
                cuisines=[
                    {
                        "name": cuisine,
                        "url": f"/cuisines/{cuisine.lower().replace(' ','-')}/",
                        "len": len(
                            [place for place in places if place["cuisine"] == cuisine]
                        ),
                    }
                    for cuisine in cuisine_names
                ]
            )
        )
    sitemap.insert(
        2,
        {
            "url": f"{SITE_URL}/cuisines/",
            "changefreq": "daily",
        },
    )

    def format_cuisine_title(cuisine):
        return f"Vegan {cuisine} food in the San Francisco Bay Area — Vegans In Love with Food"

    def format_cuisine_description(meta):
        return f"Read our reviews on vegan {cuisine} food and others in the Bay Area from V.I.L.F!"

    cuisine_template = env.get_template("cuisine.html")

    for cuisine in cuisine_names:
        slug = cuisine.lower().replace(" ", "-")
        cuisine_places = [
            place["name"] for place in places if place["cuisine"] == cuisine
        ]
        rendered = cuisine_template.render(
            title=format_cuisine_title(cuisine),
            description=format_cuisine_description(cuisine),
            cuisine=cuisine,
            places=sorted(
                [place for place in places if place["cuisine"] == cuisine],
                key=lambda item: (-item["taste"], -item["value"], item["slug"]),
            ),
        )
        cuisine_dir = build_dir / "cuisines" / slug
        cuisine_dir.mkdir(exist_ok=True, parents=True)
        with open(cuisine_dir / "index.html", "w") as o:
            o.write(rendered)

        sitemap.append(
            {
                "url": f"{SITE_URL}/cuisines/{slug}/",
                "changefreq": "daily",
            }
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

    # neighborhood pages
    neighborhood_names = sorted(set([place["area"] for place in places]))
    
    neighborhoods_dir = build_dir / "neighborhoods"
    neighborhoods_dir.mkdir(exist_ok=True, parents=True)
    
    def format_neighborhood_title(neighborhood):
        return f"Vegan food in {neighborhood} — San Francisco Bay Area — Vegans In Love with Food"

    def format_neighborhood_description(neighborhood):
        return f"Find the best vegan restaurants in {neighborhood}, San Francisco Bay Area. Curated reviews from V.I.L.F!"

    neighborhood_template = env.get_template("neighborhood.html")
    
    # Track neighborhoods with 3+ restaurants for the index page
    neighborhoods_with_pages = []

    for neighborhood in neighborhood_names:
        slug = neighborhood.lower().replace(" ", "-")
        neighborhood_places = [
            place for place in places if place["area"] == neighborhood
        ]
        
        # Only create pages for neighborhoods with 3+ restaurants
        if len(neighborhood_places) >= 3:
            rendered = neighborhood_template.render(
                title=format_neighborhood_title(neighborhood),
                description=format_neighborhood_description(neighborhood),
                neighborhood=neighborhood,
                places=sorted(
                    neighborhood_places,
                    key=lambda item: (-item["taste"], -item["value"], item["slug"]),
                ),
            )
            neighborhood_dir = build_dir / "neighborhoods" / slug
            neighborhood_dir.mkdir(exist_ok=True, parents=True)
            with open(neighborhood_dir / "index.html", "w") as o:
                o.write(rendered)

            sitemap.append(
                {
                    "url": f"{SITE_URL}/neighborhoods/{slug}/",
                    "changefreq": "weekly",
                }
            )
            
            # Track for index page
            neighborhoods_with_pages.append({
                "name": neighborhood,
                "url": f"/neighborhoods/{slug}/",
                "len": len(neighborhood_places)
            })

    # Create neighborhoods index page
    with open(neighborhoods_dir / "index.html", "w") as o:
        o.write(
            env.get_template("neighborhood-list.html").render(
                neighborhoods=sorted(neighborhoods_with_pages, key=lambda x: -x["len"])
            )
        )
    sitemap.append(
        {
            "url": f"{SITE_URL}/neighborhoods/",
            "changefreq": "weekly",
        }
    )

    with open(build_dir / "robots.txt", "w") as o:
        robots_content = f"""User-agent: *
Disallow: /raw/
Disallow: /scripts/
Disallow: /*.geojson$

# Allow all other content
Allow: /

# Sitemap
Sitemap: {SITE_URL}/sitemap.xml

# Crawl-delay for polite crawling
Crawl-delay: 1"""
        o.write(robots_content)

    print(f"Done building VILF with {len(places)} places")

    # Define the mapping of taste values to names
    taste_labels = {0: "DNR", 1: "SGFI", 2: "Good", 3: "Phenomenal"}

    # Initialize taste counts for each label
    taste_counts = {0: 0, 1: 0, 2: 0, 3: 0}

    # Count the occurrences of each 'taste' value
    for place in places:
        taste = place['taste']
        if taste in taste_counts:
            taste_counts[taste] += 1

    # Calculate the total number of entries
    total_entries = len(places)

    # Calculate and print the percentage for each 'taste' value in order
    for taste in sorted(taste_labels.keys()):
        percentage = round((taste_counts[taste] / total_entries) * 100)
        print(f"{taste_labels[taste]}: {percentage}%")

if __name__ == "__main__":
    build()
