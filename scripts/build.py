#!/bin/python3

import json
import os
import re
import shutil
import subprocess
from datetime import date
from pathlib import Path

import click
import yaml
from jinja2 import Environment, FileSystemLoader
from markdown2 import markdown
from mdplain import plain
from PIL import Image
from tqdm import tqdm

from .schema import (
    BOOLEAN_COLORS,
    BOOLEAN_LABELS,
    FADED_COLOR,
    RATING_COLORS,
    TASTE_LABELS,
    VALUE_LABELS,
    load_place,
    validate_place,
    validate_unique,
)

SITE_URL = "https://vilf.org"


def parse_git_dates(log: str) -> dict[str, str]:
    """Map each path in `git log --format=%cs --name-only` output to its newest commit date."""
    dates: dict[str, str] = {}
    current = None
    for line in log.splitlines():
        line = line.strip()
        if not line:
            continue
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", line):
            current = line
        elif current:
            dates.setdefault(line, current)  # the log is newest-first, so the first sighting wins
    return dates


def git_modified_dates(path="places") -> dict[str, str]:
    """Last commit date per file under path (repo-relative keys), or {} when git is unavailable."""
    try:
        log = subprocess.run(
            ["git", "log", "--format=%cs", "--name-only", "--", path],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return {}
    return parse_git_dates(log)


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
                description="An error occurred.",
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
                url="/about/",
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

    def rating_to_formatting(rating, rating_labels):
        return rating_labels[rating], RATING_COLORS[rating]

    def rating_html(rating, rating_labels):
        return "&nbsp;".join(
            [
                f'<span style="color: {color if rating == ix else FADED_COLOR}" aria-hidden="{"false" if rating == ix else "true"}">{label}</span>'
                for ix, (label, color) in enumerate(zip(rating_labels, RATING_COLORS))
            ]
        )

    def boolean_to_formatting(boolean):
        return BOOLEAN_LABELS[boolean], BOOLEAN_COLORS[boolean]

    def boolean_html(boolean):
        return " ".join(
            [
                f'<span style="color: {color if boolean == ix else FADED_COLOR}" aria-hidden="{"false" if boolean == ix else "true"}">{label}</span>'
                for ix, (label, color) in enumerate(zip(BOOLEAN_LABELS, BOOLEAN_COLORS))
            ]
        )

    def format_title(meta):
        return f'{meta["name"]} — Tasty vegan food in {meta["area"]}, in the San Francisco Bay Area — Vegans In Love with Food'

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

    def format_verdict(meta):
        taste = ["Do not recommend", "Something going for it", "Good taste", "Phenomenal taste"]
        booze = "booze available" if meta["drinks"] else "no booze"
        return f'Verdict: {taste[meta["taste"]]}, {meta["value_label"]} value, {booze}.'

    assert (
        format_verdict({"taste": 2, "value_label": "Fine", "drinks": True})
        == "Verdict: Good taste, Fine value, booze available."
    )

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

    place_problems = 0
    # one git call for every place; uncommitted or out-of-repo files fall back to visited
    modified_dates = git_modified_dates()

    for place_md in Path("places").glob("*.md"):
        try:
            slug = place_md.parts[-1][:-3]
            relative_url = f"/places/{slug}/"
            meta, md = load_place(place_md)
            problems = validate_place(meta, md, slug)
            if problems:
                for problem in problems:
                    print(place_md.name, problem)
                place_problems += len(problems)
                continue
            meta["url"] = relative_url
            meta["slug"] = slug
            meta["geodata"] = format_geodata(meta)
            meta["phone_display"] = format_phone_number(meta)
            visited = date.fromisoformat(meta["visited"])
            meta["visited_display"] = format_visited(visited)
            meta["review_age"] = (date.today() - visited).days
            meta["modified"] = modified_dates.get(str(place_md), meta["visited"])
            meta["taste_label"], meta["taste_color"] = rating_to_formatting(
                meta["taste"], TASTE_LABELS
            )
            meta["value_label"], meta["value_color"] = rating_to_formatting(
                meta["value"], VALUE_LABELS
            )
            meta["drinks_label"], meta["drinks_color"] = boolean_to_formatting(
                meta["drinks"]
            )
            meta["verdict"] = format_verdict(meta)
            html = markdown(md.strip())
            meta["md"] = md.strip()
            meta["blurb"] = format_blurb(md)
            meta["alt_text"] = format_alt_text(meta, md)
            meta["food_image_path"] = get_fp_food_image(slug)
            meta["food_thumb_path"] = get_fp_food_thumb(slug)
            rendered = place_template.render(
                **meta,
                title=format_title(meta),
                description=format_description_with_dishes(meta, md),
                taste_html=rating_html(meta["taste"], TASTE_LABELS),
                value_html=rating_html(meta["value"], VALUE_LABELS),
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
                    "lastmod": meta["modified"],
                }
            )
        except Exception as e:
            print(place_md.name, e)
            place_problems += 1

    if place_problems:
        print(f"Build failed: {place_problems} problem(s) in places/, see above")
        raise SystemExit(1)

    problems = validate_unique(places)
    for problem in problems:
        print(problem)
    if problems:
        print(f"Build failed: {len(problems)} uniqueness problem(s)")
        raise SystemExit(1)

    # Closed places keep their page (with a banner) but stay out of the map, the
    # best/latest/cuisine/neighborhood lists and llms.txt.
    all_places = places
    places = [place for place in all_places if not place.get("closed")]
    print(f"{len(places)} open, {len(all_places) - len(places)} closed")

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
        sorted_places = sorted(
            places,
            key=lambda item: (-item["taste"], -item["value"], item["slug"]),
        )
        o.write(
            env.get_template("best.html").render(
                title="Vegans In Love with Food",
                description=f"The best {len(sorted_places)} restaurants for vegan food in the San Francisco Bay Area with V.I.L.F!",
                url="/best/",
                places=sorted_places,
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
                url="/latest/",
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
                url="/cuisines/",
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

    def format_cuisine_description(cuisine):
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
            url=f"/cuisines/{slug}/",
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
                url=f"/neighborhoods/{slug}/",
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
                title="Vegan Food by Neighborhood in San Francisco Bay Area — V.I.L.F",
                description=f"Find the best vegan restaurants in each neighborhood in the San Francisco Bay Area from V.I.L.F!",
                url="/neighborhoods/",
                neighborhoods=sorted(neighborhoods_with_pages, key=lambda x: -x["len"])
            )
        )
    sitemap.append(
        {
            "url": f"{SITE_URL}/neighborhoods/",
            "changefreq": "weekly",
        }
    )

    # AI-assistant outputs: llms.txt, llms-full.txt, places/<slug>.md, places.json
    intro = (
        "# Vegans In Love with Food\n"
        "\n"
        "> Vegan restaurant reviews for the San Francisco Bay Area, rated on taste and value.\n"
        "\n"
        "Every review rates a restaurant on two scales. Taste: DNR (Do Not Recommend), "
        "SGFI (Something Going For It), Good or Phenomenal. Value: Bad, Fine, Good or "
        "Phenomenal. 'Booze' says whether alcohol is available. Reviews are listed best first.\n"
    )

    def place_markdown(place, heading):
        address = ", ".join(x for x in [place["address"], place["area"], place["city"]] if x)
        return (
            f"{heading} {place['name']}\n"
            "\n"
            f"- URL: {SITE_URL}{place['url']}\n"
            f"- Cuisine: {place['cuisine']}\n"
            f"- Address: {address}\n"
            f"- Taste: {place['taste_label']}\n"
            f"- Value: {place['value_label']}\n"
            f"- Booze: {place['drinks_label']}\n"
            f"- Last visited: {place['visited_display']}\n"
            + ("- Status: permanently closed\n" if place.get("closed") else "")
            + f"- {place['verdict']}\n"
            "\n"
            f"{place['md']}\n"
        )

    llms_lines = [intro, "## Pages", ""]
    for label, path in [
        ("Map", "/"),
        ("Best", "/best/"),
        ("Latest", "/latest/"),
        ("Cuisines", "/cuisines/"),
        ("Neighborhoods", "/neighborhoods/"),
        ("About", "/about/"),
    ]:
        llms_lines.append(f"- [{label}]({SITE_URL}{path})")
    llms_lines += [
        "",
        "## Data",
        "",
        f"- [places.json]({SITE_URL}/places.json): every place as JSON",
        f"- [llms-full.txt]({SITE_URL}/llms-full.txt): every review in full",
        "",
        "## Reviews",
        "",
    ]
    for place in sorted_places:
        llms_lines.append(
            f"- [{place['name']}]({SITE_URL}{place['url']}): {place['cuisine']} in {place['area']}. "
            f"Taste: {place['taste_label']}. Value: {place['value_label']}."
        )
    (build_dir / "llms.txt").write_text("\n".join(llms_lines) + "\n", encoding="utf-8")

    (build_dir / "llms-full.txt").write_text(
        intro + "\n" + "\n".join(place_markdown(place, "##") for place in sorted_places),
        encoding="utf-8",
    )

    for place in all_places:
        (build_dir / "places" / f"{place['slug']}.md").write_text(
            place_markdown(place, "#"), encoding="utf-8"
        )

    places_json = [
        {
            "name": place["name"],
            "slug": place["slug"],
            "closed": bool(place.get("closed")),
            "url": f"{SITE_URL}{place['url']}",
            "cuisine": place["cuisine"],
            "area": place["area"],
            "city": place["city"],
            "address": place["address"],
            "lat": place["lat"],
            "lon": place["lon"],
            "taste": place["taste"],
            "taste_label": place["taste_label"],
            "value": place["value"],
            "value_label": place["value_label"],
            "drinks": place["drinks"],
            "visited": place["visited"],
            "modified": place["modified"],
            "phone": place["phone"],
            "menu": place["menu"],
            "website": place["website"],
            "image": (
                f"{SITE_URL}{place['food_image_path'].replace('.webp', '.jpg')}"
                if place["food_image_path"]
                else None
            ),
        }
        for place in sorted(all_places, key=lambda item: item["name"].lower())
    ]
    (build_dir / "places.json").write_text(
        json.dumps(places_json, indent=1, ensure_ascii=False), encoding="utf-8"
    )

    with open(build_dir / "robots.txt", "w") as o:
        robots_content = f"""# AI crawlers (GPTBot, ClaudeBot, Claude-Web, PerplexityBot, Google-Extended, CCBot)
# are welcome. Machine-readable copies of this site are published at
# /llms.txt, /llms-full.txt and /places.json. Do not add Disallow rules for these agents.

User-agent: *
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
    taste_labels = dict(enumerate(TASTE_LABELS))

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
    build_vilf()
