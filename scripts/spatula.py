"""
The `spatula` command: turn a Google Places search into a new places/<slug>.md.

Search (or --place-id) -> duplicate check -> review-field prompts -> write the
frontmatter via scripts.schema -> print what is still to do. Optionally copies
the food photo into raw/food/<slug>.jpg. All Google access goes through
scripts.places; GOOGLE_PLACES_API_KEY must be set (a .env at the repo root works).
"""

import io
import re
from collections.abc import Callable, Iterable
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlparse

import click
import requests
from PIL import Image
from unidecode import unidecode

from .places import (
    CONTACT_FIELDS,
    CORE_FIELDS,
    Place,
    PlacesError,
    distance_m,
    get_place,
    search_text,
)
from .schema import TASTE_LABELS, VALUE_LABELS, load_place, validate_place, write_place

BODY = "\n<REVIEW>\n"
PHOTO_DIR = Path("raw/food")
DUPLICATE_RADIUS_M = 30
MAX_RESULTS = 5
BOLD_PROBLEM = "taste: highlight a dish in bold (**...**) when taste >= 1"


def slugify(name: str, street: str | None = None) -> str:
    """The historical filename normalisation: ascii, drop punctuation, dashes, lowercase."""
    base = name + ("-" + street if street else "")
    base = unidecode(base)
    base = re.sub(r"[\.,\'\"]", "", base)  # remove punctuation
    base = re.sub(r"[^\w\-]", "-", base)  # non-alphanumerics become dashes
    base = re.sub(r"(\-{2,})", "-", base)  # collapse dashes
    return base.lower()


def unique_name(base: str, exists: Callable[[str], bool]) -> str:
    """base, or base-N for the first N whose name `exists` rejects (a trailing -N is stripped first)."""
    name = base
    appendage = 0
    while exists(name):
        name = re.split(r"-\d+$", name)[0] + f"-{appendage}"
        appendage += 1
    return name


def unique_path(directory, base: str) -> Path:
    """<directory>/<base>.md, or <base>-N.md for the first N that does not exist yet."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stem = unique_name(base, lambda name: (directory / f"{name}.md").exists())
    return directory / f"{stem}.md"


def query_from_maps_url(text: str) -> str | None:
    """'https://www.google.com/maps/place/Lion+Dance+Caf%C3%A9/@37.8,...' -> 'Lion Dance Café'."""
    m = re.search(r"^https?://\S*?/maps/place/([^/?#]+)", text.strip())
    return unquote(m.group(1).replace("+", " ")) if m else None


def pick_place(query: str, *, search=search_text) -> Place:
    """Search until exactly one place is chosen; several results become a numbered menu."""
    while True:
        results = search(query, max_results=MAX_RESULTS)
        if len(results) == 1:
            return results[0]
        if results:
            click.echo("\n0: Search again")
            for i, p in enumerate(results, 1):
                click.echo(f"{i}: {p.name} at {p.street_address}, {p.city}")
            n = click.prompt("Pick one", type=click.IntRange(0, len(results)))
            if n:
                return results[n - 1]
        else:
            click.echo(f"No results for {query!r}.")
        query = click.prompt("Search again")
        query = query_from_maps_url(query) or query


def place_to_meta(place: Place, *, city_as_area: bool = False) -> dict:
    """The frontmatter dict for a fresh review; review fields are left for the prompts."""
    return {
        "name": place.name,
        "cuisine": None,
        "address": place.street_address,
        "area": place.city if city_as_area else None,
        "lat": place.lat,
        "lon": place.lon,
        "phone": place.phone,
        "menu": None,
        "drinks": None,
        "visited": None,
        "taste": None,
        "value": None,
        "instagram_published": False,
        "city": place.city,
        "place_id": place.place_id,
        "website": place.website,  # None unless CONTACT fields were fetched
    }


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def find_duplicate(meta: dict, rows: Iterable[dict]) -> str | None:
    """Slug of the first row (slug, place_id, lat, lon) with the same place_id or within DUPLICATE_RADIUS_M metres."""
    for other in rows:
        if meta.get("place_id") and other.get("place_id") == meta["place_id"]:
            return other["slug"]
        coords = (meta.get("lat"), meta.get("lon"), other.get("lat"), other.get("lon"))
        if all(_is_number(c) for c in coords) and distance_m(*coords) <= DUPLICATE_RADIUS_M:
            return other["slug"]
    return None


def find_duplicate_in_dir(meta: dict, places_dir) -> Path | None:
    """First existing file in places_dir that find_duplicate flags; unreadable files are skipped."""
    rows = []
    for path in sorted(Path(places_dir).glob("*.md")):
        try:
            other, _ = load_place(path)
        except Exception:
            continue
        rows.append(
            {
                "slug": path.stem,
                "place_id": other.get("place_id"),
                "lat": other.get("lat"),
                "lon": other.get("lon"),
            }
        )
    slug = find_duplicate(meta, rows)
    return Path(places_dir) / f"{slug}.md" if slug else None


def _legend(labels: list[str]) -> str:
    return " ".join(f"{i}={label}" for i, label in enumerate(labels))


def prompt_review_fields(meta: dict) -> dict:
    """Ask for the fields only the reviewer knows; returns an updated copy of meta."""
    cuisine = click.prompt("cuisine")
    area = click.prompt("area (neighborhood, required)", default=meta.get("city") or None)
    drinks = click.prompt("drinks (serves alcohol)", type=click.BOOL)
    click.echo(f"taste: {_legend(TASTE_LABELS)}")
    taste = click.prompt("taste", type=click.IntRange(0, 3))
    click.echo(f"value: {_legend(VALUE_LABELS)}")
    value = click.prompt("value", type=click.IntRange(0, 3))
    while True:
        visited = click.prompt("visited", default=date.today().isoformat())
        try:
            date.fromisoformat(visited)
            break
        except ValueError:
            click.echo("Enter an ISO date like 2024-03-31")
    return {
        **meta,
        "cuisine": cuisine,
        "area": area,
        "drinks": drinks,
        "taste": taste,
        "value": value,
        "visited": visited,
    }


def photo_dest(slug: str, *, force: bool = False) -> Path:
    dest = PHOTO_DIR / f"{slug}.jpg"
    if dest.exists() and not force:
        raise click.ClickException(f"{dest} already exists; use --force to overwrite")
    return dest


def read_photo(src: str) -> tuple[Image.Image, bytes, str]:
    """Fetch and decode a local path or http(s) URL; returns (image, raw bytes, suffix).

    Decoding happens here, before anything is written, so a HEIC or an HTML
    error page saved as .jpg fails cleanly instead of after the .md exists.
    """
    if src.startswith(("http://", "https://")):
        try:
            resp = requests.get(src, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise click.ClickException(f"cannot download photo {src}: {e}") from e
        data, suffix = resp.content, Path(urlparse(src).path).suffix
    else:
        try:
            data, suffix = Path(src).read_bytes(), Path(src).suffix
        except OSError as e:
            raise click.ClickException(f"cannot read photo {src}: {e}") from e
    try:
        im = Image.open(io.BytesIO(data))
        im.load()  # a truncated file only fails here, not in open()
    except (OSError, ValueError) as e:  # UnidentifiedImageError is an OSError
        raise click.ClickException(f"cannot decode photo {src} as an image: {e}") from e
    return im, data, suffix


def write_photo(im: Image.Image, data: bytes, suffix: str, dest: Path) -> Path:
    """Write a JPEG to dest (copying .jpg/.jpeg verbatim) and warn if wider than 16:9."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    w, h = im.size
    if suffix.lower() in (".jpg", ".jpeg"):
        dest.write_bytes(data)
    else:
        im.convert("RGB").save(dest, "JPEG", quality=95)
    if w / h > 16 / 9:
        click.echo(
            f"Warning: {dest} is {w}x{h}, wider than 16:9; the build asserts that ratio, so crop it"
        )
    return dest


def save_photo(src: str, slug: str, *, force: bool = False) -> Path:
    """Copy or download src to raw/food/<slug>.jpg."""
    dest = photo_dest(slug, force=force)
    return write_photo(*read_photo(src), dest)


def _coords(place: Place) -> str:
    if _is_number(place.lat) and _is_number(place.lon):
        return f"{place.lat:.6f}, {place.lon:.6f}"
    return "n/a"


def print_place(place: Place) -> None:
    click.echo(f"\nName = {place.name}")
    click.echo(f"Address = {place.street_address}")
    click.echo(f"City = {place.city}")
    click.echo(f"State = {place.state}")
    click.echo(f"Zip code = {place.postal_code}")
    click.echo(f"Phone = {place.phone}")
    click.echo(f"Website = {place.website}")
    click.echo(f"Status = {place.business_status}")
    click.echo(f"Lat, lon = {_coords(place)}")
    click.echo(f"Maps = {place.maps_url}")


@click.command()
@click.option(
    "--search-query",
    "-s",
    default=None,
    help="Google Places text search (name and city, or a pasted Google Maps URL). Prompted if absent.",
)
@click.option("--place-id", default=None, help="Skip the search and use this Google place id.")
@click.option(
    "--details/--no-details",
    default=True,
    show_default=True,
    help="Also fetch phone and website (Enterprise billing tier, one call per new review).",
)
@click.option(
    "--city-as-area/--no-city-as-area",
    default=False,
    help="Prefill the 'area' field with the city (you probably want a neighborhood instead).",
)
@click.option(
    "--street-in-filename/--no-street-in-filename",
    default=False,
    help="Append the street address to the filename slug (useful for chains).",
)
@click.option(
    "--manual-filename",
    default=None,
    help="Write to this path instead of an autogenerated <directory>/<slug>.md.",
)
@click.option(
    "--directory",
    default="./places/",
    show_default=True,
    help="Output directory. Duplicate detection only looks at the .md files in this directory.",
)
@click.option(
    "--photo",
    default=None,
    metavar="PATH_OR_URL",
    help="Food photo (local file or http(s) URL) to save as raw/food/<slug>.jpg.",
)
@click.option(
    "--prompt/--no-prompt",
    default=True,
    show_default=True,
    help="Ask for cuisine, area, drinks, taste, value and visited; --no-prompt leaves them blank.",
)
@click.option("--ask-first/--no-ask-first", default=False, help="Confirm before writing the file.")
@click.option(
    "--force",
    is_flag=True,
    help="Ignore duplicate detection and overwrite an existing raw/food photo.",
)
def scrape_and_gen_md(
    search_query,
    place_id,
    details,
    city_as_area,
    street_in_filename,
    manual_filename,
    directory,
    photo,
    prompt,
    ask_first,
    force,
):
    """Look a restaurant up in Google Places and write a new review file.

    Needs GOOGLE_PLACES_API_KEY in the environment or in .env at the repo root.
    The review body is left as a <REVIEW> placeholder for you to write.
    """
    fields = CONTACT_FIELDS if details else CORE_FIELDS
    try:
        if place_id:
            place = get_place(place_id, fields=fields)
        else:
            query = (
                search_query
                or click.prompt("Search Google Places (name and city, or a Google Maps URL)")
            ).strip()
            query = query_from_maps_url(query) or query
            place = pick_place(query, search=search_text)
            if details:
                place = get_place(place.place_id, fields=CONTACT_FIELDS)
    except PlacesError as e:
        raise click.ClickException(str(e))

    if not place.name:
        raise click.ClickException("Google returned no name for this place")
    if place.lat is None or place.lon is None:
        raise click.ClickException(
            f"Google returned no coordinates for {place.name}; cannot write a valid file"
        )
    print_place(place)

    meta = place_to_meta(place, city_as_area=city_as_area)
    if manual_filename:
        path = Path(manual_filename).with_suffix(".md")
        path.parent.mkdir(parents=True, exist_ok=True)
    else:
        street = place.street_address if street_in_filename else None
        path = unique_path(directory, slugify(place.name, street))

    if not force:
        dup = find_duplicate_in_dir(meta, directory)
        if dup:
            raise click.ClickException(
                f"{dup} already covers this place (same place_id or within "
                f"{DUPLICATE_RADIUS_M} m); use --force to write anyway"
            )
    # Fetch and decode the photo before prompting, so a collision or an unreadable
    # image never follows six answered questions or a written .md file.
    if photo:
        dest = photo_dest(path.stem, force=force)
        photo_data = read_photo(photo)

    if prompt:
        meta = prompt_review_fields(meta)
    if ask_first and not click.confirm(f"Write {path}?", default=True):
        click.echo("Not writing markdown.")
        return

    write_place(path, meta, BODY)
    if photo:
        write_photo(*photo_data, dest)

    written_meta, written_body = load_place(path)
    problems = validate_place(written_meta, written_body, path.stem)
    if problems:
        click.echo("\nTo do before this file builds:")
        for problem in problems:
            if problem == BOLD_PROBLEM:
                problem = "write the review (body is still the <REVIEW> placeholder) and bold at least one dish with **...**"
            click.echo(f"- {problem}")
    click.echo(f"\nWrote {path}")


if __name__ == "__main__":
    scrape_and_gen_md()
