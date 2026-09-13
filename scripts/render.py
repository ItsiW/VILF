"""Render the site from a list of snapshot-format place dicts.

A snapshot row is every scripts/schema.py field plus slug, body (markdown after
the frontmatter), photo_key (None = no photo), photo_width/height/crop_y and
created_at/updated_at/published_at. Nothing here touches images, git or the
places/ directory: the caller (build.py, or the admin app) assembles the rows
and processes photos; this module only writes HTML, feeds and the map data.
"""

import json
import re
import shutil
from datetime import date
from pathlib import Path
from typing import NamedTuple

from jinja2 import Environment, FileSystemLoader
from markdown2 import markdown
from mdplain import plain

from .schema import (
    BOOLEAN_COLORS,
    BOOLEAN_LABELS,
    FADED_COLOR,
    RATING_COLORS,
    TASTE_LABELS,
    VALUE_LABELS,
    split_frontmatter,
    validate_place,
    validate_unique,
)

SITE_URL = "https://vilf.org"

# Row keys that are not frontmatter; everything else in a row goes through validate_place.
SNAPSHOT_ONLY_KEYS = frozenset({
    "slug", "body", "photo_key", "photo_width", "photo_height", "photo_crop_y",
    "created_at", "updated_at", "published_at",
})

INTRO = (
    "# Vegans In Love with Food\n"
    "\n"
    "> Vegan restaurant reviews for the San Francisco Bay Area, rated on taste and value.\n"
    "\n"
    "Every review rates a restaurant on two scales. Taste: DNR (Do Not Recommend), "
    "SGFI (Something Going For It), Good or Phenomenal. Value: Bad, Fine, Good or "
    "Phenomenal. 'Booze' says whether alcohol is available. Reviews are listed best first.\n"
)

ROBOTS = """# AI crawlers (GPTBot, ClaudeBot, Claude-Web, PerplexityBot, Google-Extended, CCBot)
# are welcome. Machine-readable copies of this site are published at
# /llms.txt, /llms-full.txt and /places.json. Do not add Disallow rules for these agents.

User-agent: *
Disallow: /raw/
Disallow: /scripts/
Disallow: /*.geojson$

# Allow all other content
Allow: /

# Sitemap
Sitemap: {site_url}/sitemap.xml

# Crawl-delay for polite crawling
Crawl-delay: 1"""


class RenderError(Exception):
    """One or more rows failed validation; .problems holds '<slug>: <problem>' lines."""

    def __init__(self, problems: list[str]):
        super().__init__(f"{len(problems)} problem(s)")
        self.problems = problems


class RenderStats(NamedTuple):
    open: int
    closed: int
    pages: int


# --- per-place formatting helpers (formerly nested in build_vilf) ---


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
    dishes = re.findall(r"\*\*(.*?)\*\*", md)
    if dishes:
        dishes_text = ", ".join(dishes[:2])  # Max 2 dishes for meta description
        return f'Read our review on {meta["name"]} featuring {dishes_text} at {meta["address"]} in {meta["area"]}, and more tasty vegan {meta["cuisine"]} food in the San Francisco Bay Area from V.I.L.F!'
    return f'Read our review on {meta["name"]} at {meta["address"]} in {meta["area"]}, and more tasty vegan {meta["cuisine"]} food in the San Francisco Bay Area from V.I.L.F!'


def format_phone_number(meta):
    # validate_place already guarantees +1 plus 10 digits
    if meta["phone"] is None:
        return
    number = meta["phone"]
    return f"({number[2:5]}) {number[5:8]}-{number[8:12]}"


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


def format_alt_text(meta, md):
    """Generate enhanced alt text with specific dishes mentioned"""
    base_alt = f"Vegan {meta['cuisine']} food at {meta['name']} in {meta['area']}, San Francisco Bay Area"
    dishes = re.findall(r"\*\*(.*?)\*\*", md)
    if dishes:
        dishes_text = ", ".join(dishes[:3])  # Max 3 dishes
        return f"{base_alt} featuring {dishes_text}"
    return base_alt


def format_cuisine_title(cuisine):
    return f"Vegan {cuisine} food in the San Francisco Bay Area — Vegans In Love with Food"


def format_cuisine_description(cuisine):
    return f"Read our reviews on vegan {cuisine} food and others in the Bay Area from V.I.L.F!"


def format_neighborhood_title(neighborhood):
    return f"Vegan food in {neighborhood} — San Francisco Bay Area — Vegans In Love with Food"


def format_neighborhood_description(neighborhood):
    return f"Find the best vegan restaurants in {neighborhood}, San Francisco Bay Area. Curated reviews from V.I.L.F!"


def md_link_text(name):
    return name.replace("[", "\\[").replace("]", "\\]")


def place_markdown(place, heading, site_url=SITE_URL):
    address = ", ".join(x for x in [place["address"], place["area"], place["city"]] if x)
    return (
        f"{heading} {place['name']}\n"
        "\n"
        f"- URL: {site_url}{place['url']}\n"
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


def enrich_place(row: dict, *, today: date, media_base_url: str = "") -> dict:
    """Add the derived display fields the templates and feeds use.

    Keys are added in a fixed order because places.geojson properties follow
    dict insertion order.
    """
    place = dict(row)
    slug = row["slug"]
    place["url"] = f"/places/{slug}/"
    place["slug"] = slug
    place["geodata"] = format_geodata(place)
    place["phone_display"] = format_phone_number(place)
    visited = date.fromisoformat(place["visited"])
    place["visited_display"] = format_visited(visited)
    place["review_age"] = (today - visited).days
    place["modified"] = row["updated_at"][:10] if row.get("updated_at") else row["visited"]
    place["taste_label"], place["taste_color"] = rating_to_formatting(place["taste"], TASTE_LABELS)
    place["value_label"], place["value_color"] = rating_to_formatting(place["value"], VALUE_LABELS)
    place["drinks_label"], place["drinks_color"] = boolean_to_formatting(place["drinks"])
    place["verdict"] = format_verdict(place)
    md = row["body"].strip()
    place["md"] = md
    place["blurb"] = format_blurb(md)
    place["alt_text"] = format_alt_text(place, md)
    if row.get("photo_key"):
        place["food_image_path"] = f"{media_base_url}/img/food/{slug}.webp"
        place["food_thumb_path"] = f"{media_base_url}/img/thumb/{slug}.webp"
    else:
        place["food_image_path"] = None
        place["food_thumb_path"] = None
    place["taste_html"] = rating_html(place["taste"], TASTE_LABELS)
    place["value_html"] = rating_html(place["value"], VALUE_LABELS)
    place["drinks_html"] = boolean_html(place["drinks"])
    return place


def render_place_page(env: Environment, place: dict, *, cuisine_names=None) -> str:
    """HTML for one enriched place (also used by the admin preview)."""
    has_cuisine_page = (
        place["cuisine"] in cuisine_names if cuisine_names is not None else not place.get("closed")
    )
    return env.get_template("place.html").render(
        **place,
        cuisine_url=(
            f"/cuisines/{place['cuisine'].lower().replace(' ', '-')}/" if has_cuisine_page else None
        ),
        title=format_title(place),
        description=format_description_with_dishes(place, place["md"]),
        content=markdown(place["md"]),
    )


def _by_rating(item):
    return (-item["taste"], -item["value"], item["slug"])


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(exist_ok=True, parents=True)
    path.write_text(text, encoding="utf-8")


def render_site(
    places: list[dict],
    out_dir: Path,
    *,
    site_url: str = SITE_URL,
    media_base_url: str = "",
    html_dir="html",
    static_dir="static",
    about_path="about.md",
    today: date | None = None,
) -> RenderStats:
    """Validate the rows, wipe out_dir, copy static_dir into it and write every page and feed."""
    today = today or date.today()
    out_dir = Path(out_dir)
    env = Environment(loader=FileSystemLoader(str(html_dir)))
    env.globals["SITE_URL"] = site_url

    problems = []
    for row in places:
        meta = {k: v for k, v in row.items() if k not in SNAPSHOT_ONLY_KEYS}
        problems += [f"{row['slug']}: {p}" for p in validate_place(meta, row["body"], row["slug"])]
    if problems:
        raise RenderError(problems)
    all_places = [enrich_place(row, today=today, media_base_url=media_base_url) for row in places]
    problems = validate_unique(all_places)
    if problems:
        raise RenderError(problems)

    shutil.rmtree(out_dir, ignore_errors=True)
    shutil.copytree(Path(static_dir), out_dir)
    pages = 0
    sitemap = []

    # Closed places keep their page (with a banner) but stay out of the map, the
    # best/latest/cuisine/neighborhood lists and llms.txt.
    places = [place for place in all_places if not place.get("closed")]
    cuisine_names = sorted({place["cuisine"] for place in places})

    # map page
    _write(
        out_dir / "index.html",
        env.get_template("map.html").render(
            title="Vegans In Love with Food",
            description="Find tasty vegan food in the San Francisco Bay Area with V.I.L.F!",
            thumbnails=[place["food_thumb_path"] for place in places if place["food_thumb_path"]],
        ),
    )
    pages += 1
    sitemap.append({"url": f"{site_url}/"})

    # error page
    _write(
        out_dir / "error.html",
        env.get_template("error.html").render(
            title="Vegans In Love with Food",
            description="An error occurred.",
        ),
    )
    pages += 1

    # about page
    meta, md = split_frontmatter(Path(about_path).read_text(encoding="utf-8"), str(about_path))
    _write(
        out_dir / "about" / "index.html",
        env.get_template("about.html").render(**meta, url="/about/", content=markdown(md.strip())),
    )
    pages += 1
    sitemap.append({"url": f"{site_url}/about/"})

    # place pages
    for place in all_places:
        _write(
            out_dir / "places" / place["slug"] / "index.html",
            render_place_page(env, place, cuisine_names=cuisine_names),
        )
        pages += 1
        sitemap.append({"url": f"{site_url}{place['url']}", "lastmod": place["modified"]})

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
                "geometry": {"type": "Point", "coordinates": [place["lon"], place["lat"]]},
                "properties": {key: value for key, value in place.items() if key in geojson_keys},
            }
            # sort reverse of by taste desc, then value desc, then alphabetical by name
            for place in sorted(places, key=_by_rating, reverse=True)
        ],
    }
    _write(out_dir / "places.geojson", json.dumps(geojson))

    # best page
    sorted_places = sorted(places, key=_by_rating)
    _write(
        out_dir / "best" / "index.html",
        env.get_template("best.html").render(
            title="Vegans In Love with Food",
            description=f"The best {len(sorted_places)} restaurants for vegan food in the San Francisco Bay Area with V.I.L.F!",
            url="/best/",
            places=sorted_places,
        ),
    )
    pages += 1
    sitemap.insert(2, {"url": f"{site_url}/best/", "changefreq": "daily"})

    # latest page
    _write(
        out_dir / "latest" / "index.html",
        env.get_template("latest.html").render(
            title="Latest Reviews from Vegans In Love with Food",
            description="Find tasty vegan food around the San Francisco Bay Area!",
            url="/latest/",
            # sort by age then standard
            places=sorted(places, key=lambda item: (item["review_age"], *_by_rating(item))),
        ),
    )
    pages += 1
    sitemap.insert(2, {"url": f"{site_url}/latest/", "changefreq": "daily"})

    # cuisines
    _write(
        out_dir / "cuisines" / "index.html",
        env.get_template("cuisine-list.html").render(
            title="Vegan food by cuisine in the Bay Area | VILF",
            description="Browse VILF's restaurant reviews by cuisine to find vegan options across the San Francisco Bay Area.",
            url="/cuisines/",
            cuisines=[
                {
                    "name": cuisine,
                    "url": f"/cuisines/{cuisine.lower().replace(' ','-')}/",
                    "len": len([place for place in places if place["cuisine"] == cuisine]),
                }
                for cuisine in cuisine_names
            ],
        ),
    )
    pages += 1
    sitemap.insert(2, {"url": f"{site_url}/cuisines/", "changefreq": "daily"})

    cuisine_template = env.get_template("cuisine.html")
    for cuisine in cuisine_names:
        slug = cuisine.lower().replace(" ", "-")
        _write(
            out_dir / "cuisines" / slug / "index.html",
            cuisine_template.render(
                title=format_cuisine_title(cuisine),
                description=format_cuisine_description(cuisine),
                url=f"/cuisines/{slug}/",
                cuisine=cuisine,
                places=sorted(
                    [place for place in places if place["cuisine"] == cuisine], key=_by_rating
                ),
            ),
        )
        pages += 1
        sitemap.append({"url": f"{site_url}/cuisines/{slug}/", "changefreq": "daily"})

    # neighborhood pages (only areas with 3+ places)
    neighborhood_names = sorted(set([place["area"] for place in places]))
    neighborhood_template = env.get_template("neighborhood.html")
    neighborhoods_with_pages = []
    for neighborhood in neighborhood_names:
        slug = neighborhood.lower().replace(" ", "-")
        neighborhood_places = [place for place in places if place["area"] == neighborhood]
        if len(neighborhood_places) >= 3:
            _write(
                out_dir / "neighborhoods" / slug / "index.html",
                neighborhood_template.render(
                    title=format_neighborhood_title(neighborhood),
                    description=format_neighborhood_description(neighborhood),
                    url=f"/neighborhoods/{slug}/",
                    neighborhood=neighborhood,
                    places=sorted(neighborhood_places, key=_by_rating),
                ),
            )
            pages += 1
            sitemap.append({"url": f"{site_url}/neighborhoods/{slug}/", "changefreq": "weekly"})
            neighborhoods_with_pages.append(
                {"name": neighborhood, "url": f"/neighborhoods/{slug}/", "len": len(neighborhood_places)}
            )

    _write(
        out_dir / "neighborhoods" / "index.html",
        env.get_template("neighborhood-list.html").render(
            title="Vegan Food by Neighborhood in San Francisco Bay Area — V.I.L.F",
            description="Find the best vegan restaurants in each neighborhood in the San Francisco Bay Area from V.I.L.F!",
            url="/neighborhoods/",
            neighborhoods=sorted(neighborhoods_with_pages, key=lambda x: -x["len"]),
        ),
    )
    pages += 1
    sitemap.append({"url": f"{site_url}/neighborhoods/", "changefreq": "weekly"})

    # Write only after every canonical HTML page has been collected.
    _write(
        out_dir / "sitemap.xml",
        env.get_template("sitemap.xml").render(
            urls=[
                (item.get("url"), item.get("lastmod", today), item.get("changefreq"))
                for item in sitemap
            ]
        ),
    )

    # AI-assistant outputs: llms.txt, llms-full.txt, places/<slug>.md, places.json
    llms_lines = [INTRO, "## Pages", ""]
    for label, path in [
        ("Map", "/"),
        ("Best", "/best/"),
        ("Latest", "/latest/"),
        ("Cuisines", "/cuisines/"),
        ("Neighborhoods", "/neighborhoods/"),
        ("About", "/about/"),
    ]:
        llms_lines.append(f"- [{label}]({site_url}{path})")
    llms_lines += [
        "",
        "## Data",
        "",
        f"- [places.json]({site_url}/places.json): every place as JSON",
        f"- [llms-full.txt]({site_url}/llms-full.txt): every review in full",
        "",
        "## Reviews",
        "",
    ]
    for place in sorted_places:
        llms_lines.append(
            f"- [{md_link_text(place['name'])}]({site_url}{place['url']}): {place['cuisine']} in {place['area']}. "
            f"Taste: {place['taste_label']}. Value: {place['value_label']}. "
            f"[markdown]({site_url}/places/{place['slug']}.md)"
        )
    _write(out_dir / "llms.txt", "\n".join(llms_lines) + "\n")
    _write(
        out_dir / "llms-full.txt",
        INTRO + "\n" + "\n".join(place_markdown(place, "##", site_url) for place in sorted_places),
    )
    for place in all_places:
        _write(out_dir / "places" / f"{place['slug']}.md", place_markdown(place, "#", site_url))

    places_json = [
        {
            "name": place["name"],
            "slug": place["slug"],
            "closed": bool(place.get("closed")),
            "url": f"{site_url}{place['url']}",
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
                f"{site_url}{place['food_image_path'].replace('.webp', '.jpg')}"
                if place["food_image_path"]
                else None
            ),
        }
        for place in sorted(all_places, key=lambda item: item["name"].lower())
    ]
    _write(out_dir / "places.json", json.dumps(places_json, indent=1, ensure_ascii=False))

    _write(out_dir / "robots.txt", ROBOTS.format(site_url=site_url))

    return RenderStats(len(places), len(all_places) - len(places), pages)
