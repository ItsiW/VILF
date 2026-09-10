"""Photo storage for the admin app: originals plus the four rendered variants.

Keys inside media storage: originals/<slug>.jpg (EXIF-free re-encode of the
upload) and img/food|thumb/<slug>.jpg|webp, which publish copies verbatim to
the site so the paths match render.enrich_place's /img/... URLs.
"""

from PIL import Image

from .images import clean_jpeg, open_photo, preview_jpeg, process_photo
from .storage import Storage

ORIGINAL_KEY = "originals/{slug}.jpg"
# (storage key, content type, process_photo output name)
VARIANTS = [
    ("img/food/{slug}.jpg", "image/jpeg", "food.jpg"),
    ("img/food/{slug}.webp", "image/webp", "food.webp"),
    ("img/thumb/{slug}.jpg", "image/jpeg", "thumb.jpg"),
    ("img/thumb/{slug}.webp", "image/webp", "thumb.webp"),
]
VARIANT_PATHS = ["/" + key for key, _, _ in VARIANTS]
CACHE_CONTROL = "public, max-age=86400"


def variant_keys(slug: str) -> list[str]:
    return [key.format(slug=slug) for key, _, _ in VARIANTS]


def _store_original_image(media: Storage, slug: str, im: Image.Image) -> dict:
    key = ORIGINAL_KEY.format(slug=slug)
    media.put(key, clean_jpeg(im), content_type="image/jpeg")
    return {"photo_key": key, "photo_width": im.size[0], "photo_height": im.size[1]}


def store_original(media: Storage, slug: str, data: bytes) -> dict:
    """Decode, drop EXIF, store as originals/<slug>.jpg; returns photo_key/width/height."""
    return _store_original_image(media, slug, open_photo(data))


def write_variants(media: Storage, slug: str, im: Image.Image, crop_y: float) -> list[str]:
    outputs = process_photo(im, crop_y)
    keys = []
    for key, content_type, name in VARIANTS:
        key = key.format(slug=slug)
        media.put(key, outputs[name], content_type=content_type, cache_control=CACHE_CONTROL)
        keys.append(key)
    return keys


def set_photo(media: Storage, slug: str, data: bytes, crop_y: float = 0.5) -> dict:
    """Store the original and the variants; returns the photo_* row fields."""
    im = open_photo(data)
    fields = _store_original_image(media, slug, im)
    write_variants(media, slug, im, crop_y)
    fields["photo_crop_y"] = float(crop_y)
    return fields


def recrop(media: Storage, row: dict, crop_y: float) -> list[str]:
    """Rewrite the variants of `row` (needs slug and photo_key) at a new crop position."""
    im = open_photo(media.get(row["photo_key"]))
    return write_variants(media, row["slug"], im, crop_y)


def delete_photo(media: Storage, slug: str, photo_key: str | None) -> None:
    """Remove the original and the four variants; missing keys are fine."""
    if photo_key:
        media.delete(photo_key)
    for key in variant_keys(slug):
        media.delete(key)


def preview(media: Storage, photo_key: str, crop_y: float, width: int = 600) -> bytes:
    """JPEG of the cropped window at `width` pixels, for the crop picker."""
    return preview_jpeg(open_photo(media.get(photo_key)), crop_y, width)
