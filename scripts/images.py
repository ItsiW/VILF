"""Photo processing: bytes in, standardised food images out.

The pipeline is the one build.py used for years (resize to 1200 wide, crop a
16:9 window, save JPEG and WebP at quality 82, thumb at 426x240), lifted out so
it can run on uploaded bytes instead of files under raw/food. New here: HEIC
input, EXIF orientation is honoured, and the vertical crop position is a
parameter (crop_y, 0..1) instead of always the centre.
"""

from io import BytesIO

import pillow_heif
from PIL import Image, ImageOps

pillow_heif.register_heif_opener()

FOOD_SIZE = (1200, 675)
THUMB_SIZE = (426, 240)
QUALITY = 82


class PhotoError(ValueError):
    """Bytes that Pillow cannot decode as an image."""


def open_photo(data: bytes) -> Image.Image:
    """Decode bytes (JPEG, PNG, HEIC, ...) into an upright RGB image."""
    try:
        im = Image.open(BytesIO(data))
        im.load()
        im = ImageOps.exif_transpose(im)
        return im.convert("RGB")
    except Exception as e:  # UnidentifiedImageError, OSError, ValueError, SyntaxError...
        raise PhotoError(f"cannot decode image: {e}") from e


def clean_jpeg(im: Image.Image, quality: int = 95) -> bytes:
    """Re-encode as a plain JPEG; no EXIF (location, camera, orientation) survives."""
    buf = BytesIO()
    im.convert("RGB").save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _fit(im: Image.Image) -> Image.Image:
    """Resize so the 16:9 window fits: width 1200 for taller images, height 675 for wider."""
    w, h = im.size
    if w / h <= FOOD_SIZE[0] / FOOD_SIZE[1]:
        # same call as the old build, default resampling included, so outputs stay identical
        return im.resize((FOOD_SIZE[0], int(FOOD_SIZE[0] * h / w)))
    return im.resize((int(FOOD_SIZE[1] * w / h), FOOD_SIZE[1]))


def crop_box(size: tuple[int, int], crop_y: float) -> tuple[int, int, int, int]:
    """The 16:9 window inside a fitted image (see _fit) as (left, top, right, bottom).

    Taller images slide vertically with crop_y (0 = top, 0.5 = centre, 1 = bottom);
    wider images are centred horizontally and ignore crop_y.
    """
    width, height = FOOD_SIZE
    w, h = size
    crop_y = min(max(float(crop_y), 0.0), 1.0)
    if h > height:
        top = int((h - height) * crop_y)
        return (0, top, width, top + height)
    if w > width:
        left = int((w - width) / 2)
        return (left, 0, left + width, height)
    return (0, 0, w, h)


def _encode(im: Image.Image, fmt: str) -> bytes:
    buf = BytesIO()
    im.save(buf, format=fmt, quality=QUALITY)
    return buf.getvalue()


def process_photo(im: Image.Image, crop_y: float = 0.5) -> dict[str, bytes]:
    """Full-size and thumbnail outputs in JPEG and WebP, keyed food.jpg/food.webp/thumb.jpg/thumb.webp."""
    im = im.convert("RGB")
    fitted = _fit(im)
    cropped = fitted.crop(crop_box(fitted.size, crop_y))
    thumb = cropped.resize(THUMB_SIZE)
    return {
        "food.jpg": _encode(cropped, "JPEG"),
        "food.webp": _encode(cropped, "WEBP"),
        "thumb.jpg": _encode(thumb, "JPEG"),
        "thumb.webp": _encode(thumb, "WEBP"),
    }


def preview_jpeg(im: Image.Image, crop_y: float, width: int = 600) -> bytes:
    """The cropped window scaled to `width` pixels wide, as JPEG (for the crop picker)."""
    im = im.convert("RGB")
    fitted = _fit(im)
    cropped = fitted.crop(crop_box(fitted.size, crop_y))
    height = int(width * FOOD_SIZE[1] / FOOD_SIZE[0])
    return _encode(cropped.resize((width, height)), "JPEG")
