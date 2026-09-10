"""scripts/images.py: decoding, orientation, cropping and parity with the old build pipeline."""

from io import BytesIO

import pillow_heif
import pytest
from PIL import Image, ImageDraw

from scripts.images import (
    FOOD_SIZE,
    THUMB_SIZE,
    PhotoError,
    clean_jpeg,
    crop_box,
    open_photo,
    preview_jpeg,
    process_photo,
)


def gradient(w, h):
    """Vertical gradient with a few blocks, so different crop windows give different bytes."""
    im = Image.linear_gradient("L").resize((w, h)).convert("RGB")
    draw = ImageDraw.Draw(im)
    draw.rectangle([0, 0, w // 3, h // 5], fill=(200, 30, 30))
    draw.rectangle([w // 2, h // 2, w - 1, h - 1], fill=(30, 30, 200))
    return im


def jpeg_bytes(im, **kw):
    buf = BytesIO()
    im.save(buf, format="JPEG", **kw)
    return buf.getvalue()


def decode(data):
    im = Image.open(BytesIO(data))
    im.load()
    return im


def test_open_photo_transposes_exif_orientation_6():
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 CW to display
    im = open_photo(jpeg_bytes(gradient(100, 80), exif=exif))
    assert im.size == (80, 100)
    assert im.mode == "RGB"


def test_open_photo_heic_round_trip():
    buf = BytesIO()
    pillow_heif.from_pillow(gradient(160, 120)).save(buf, format="HEIF")
    im = open_photo(buf.getvalue())
    assert im.size == (160, 120)
    assert im.mode == "RGB"


def test_open_photo_rejects_garbage():
    with pytest.raises(PhotoError):
        open_photo(b"not an image")
    with pytest.raises(PhotoError):
        open_photo(b"")


def test_clean_jpeg_drops_exif():
    exif = Image.Exif()
    exif[0x0112] = 6
    exif[0x010F] = "ACME Camera"
    im = decode(jpeg_bytes(gradient(100, 80), exif=exif))
    assert im.getexif()[0x010F] == "ACME Camera"
    cleaned = decode(clean_jpeg(im))
    assert cleaned.format == "JPEG"
    assert 0x0112 not in cleaned.getexif() and 0x010F not in cleaned.getexif()


def test_crop_box_taller():
    assert crop_box((1200, 900), 0) == (0, 0, 1200, 675)
    assert crop_box((1200, 900), 0.5) == (0, 112, 1200, 787)
    assert crop_box((1200, 900), 1) == (0, 225, 1200, 900)
    assert crop_box((1200, 900), -3) == crop_box((1200, 900), 0)
    assert crop_box((1200, 900), 7) == crop_box((1200, 900), 1)


def test_crop_box_exact():
    for crop_y in [0, 0.5, 1]:
        assert crop_box((1200, 675), crop_y) == (0, 0, 1200, 675)


def test_crop_box_wider():
    for crop_y in [0, 0.5, 1]:
        assert crop_box((2000, 675), crop_y) == (400, 0, 1600, 675)


def test_process_photo_sizes_and_formats():
    outputs = process_photo(gradient(1600, 1200))
    assert set(outputs) == {"food.jpg", "food.webp", "thumb.jpg", "thumb.webp"}
    for key, fmt, size in [
        ("food.jpg", "JPEG", FOOD_SIZE),
        ("food.webp", "WEBP", FOOD_SIZE),
        ("thumb.jpg", "JPEG", THUMB_SIZE),
        ("thumb.webp", "WEBP", THUMB_SIZE),
    ]:
        im = decode(outputs[key])
        assert (im.format, im.size) == (fmt, size), key
    top = process_photo(gradient(1600, 1200), 0)
    bottom = process_photo(gradient(1600, 1200), 1)
    assert top["food.jpg"] != bottom["food.jpg"]
    assert top["thumb.webp"] != bottom["thumb.webp"]


def test_process_photo_wide_image():
    outputs = process_photo(gradient(3200, 900))
    assert decode(outputs["food.jpg"]).size == FOOD_SIZE
    assert decode(outputs["thumb.jpg"]).size == THUMB_SIZE


def old_pipeline(data):
    """build.py's original centre-crop code, verbatim, on JPEG bytes."""
    target, thumb_target, quality = (1200, 675), (426, 240), 82
    with Image.open(BytesIO(data)) as im:
        assert im.size[0] / im.size[1] <= 16 / 9
        im = im.convert("RGB")
        im = im.resize((target[0], int(target[0] * im.size[1] / im.size[0])))
        pixels_to_crop = int((im.size[1] - target[1]) / 2)
        cropped = im.crop((0, pixels_to_crop, target[0], target[1] + pixels_to_crop))
        out = {}
        for key, image in [("food", cropped), ("thumb", cropped.resize(thumb_target))]:
            for ext, fmt in [("jpg", "JPEG"), ("webp", "WEBP")]:
                buf = BytesIO()
                image.save(buf, format=fmt, quality=quality)
                out[f"{key}.{ext}"] = buf.getvalue()
        return out


def test_process_photo_matches_old_pipeline():
    data = jpeg_bytes(gradient(1600, 1200), quality=90)
    assert process_photo(open_photo(data), 0.5) == old_pipeline(data)


def test_preview_jpeg():
    im = gradient(1600, 1200)
    preview = decode(preview_jpeg(im, 0.5, width=600))
    assert (preview.format, preview.size) == ("JPEG", (600, 337))
    assert preview_jpeg(im, 0) != preview_jpeg(im, 1)
