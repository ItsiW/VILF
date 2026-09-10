from io import BytesIO

import pillow_heif
import pytest
from PIL import Image

from scripts import photos
from scripts.images import PhotoError
from scripts.storage import LocalStorage


class RecordingStorage(LocalStorage):
    """LocalStorage that remembers the content type and cache control of every put."""

    def __init__(self, root):
        super().__init__(root)
        self.puts = {}

    def put(self, key, data, *, content_type, cache_control=None):
        self.puts[key] = (content_type, cache_control)
        super().put(key, data, content_type=content_type, cache_control=cache_control)


@pytest.fixture
def media(tmp_path):
    return RecordingStorage(tmp_path / "media")


def gradient(w, h):
    im = Image.new("RGB", (w, h))
    px = im.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (x * 255 // max(w - 1, 1), y * 255 // max(h - 1, 1), 128)
    return im


def jpeg_with_exif(im):
    exif = Image.Exif()
    exif[0x0112] = 6  # orientation: rotate 90 CW on display
    exif[0x8825] = {1: "N"}  # GPS IFD
    buf = BytesIO()
    im.save(buf, format="JPEG", exif=exif.tobytes())
    return buf.getvalue()


def test_set_photo_strips_exif_and_writes_variants(media):
    data = jpeg_with_exif(gradient(1000, 700))
    fields = photos.set_photo(media, "lion", data)
    assert fields == {
        "photo_key": "originals/lion.jpg",
        "photo_width": 700,  # orientation 6 applied: width and height swap
        "photo_height": 1000,
        "photo_crop_y": 0.5,
    }
    original = Image.open(BytesIO(media.get("originals/lion.jpg")))
    assert original.size == (700, 1000)
    assert dict(original.getexif()) == {}
    assert media.puts["originals/lion.jpg"] == ("image/jpeg", None)

    expected = {
        "img/food/lion.jpg": ("image/jpeg", (1200, 675)),
        "img/food/lion.webp": ("image/webp", (1200, 675)),
        "img/thumb/lion.jpg": ("image/jpeg", (426, 240)),
        "img/thumb/lion.webp": ("image/webp", (426, 240)),
    }
    assert photos.variant_keys("lion") == list(expected)
    for key, (content_type, size) in expected.items():
        assert media.puts[key] == (content_type, photos.CACHE_CONTROL)
        assert Image.open(BytesIO(media.get(key))).size == size


def test_recrop_rewrites_variants(media):
    buf = BytesIO()
    gradient(400, 900).save(buf, format="JPEG")
    photos.set_photo(media, "tall", buf.getvalue(), crop_y=0.0)
    top = media.get("img/food/tall.jpg")
    row = {"slug": "tall", "photo_key": "originals/tall.jpg"}
    keys = photos.recrop(media, row, 1.0)
    assert keys == photos.variant_keys("tall")
    assert media.get("img/food/tall.jpg") != top
    assert Image.open(BytesIO(media.get("img/food/tall.jpg"))).size == (1200, 675)


def test_delete_photo_removes_all_and_tolerates_missing(media):
    buf = BytesIO()
    gradient(800, 600).save(buf, format="PNG")
    fields = photos.set_photo(media, "gone", buf.getvalue())
    keys = [fields["photo_key"]] + photos.variant_keys("gone")
    assert all(media.exists(k) for k in keys)
    photos.delete_photo(media, "gone", fields["photo_key"])
    assert not any(media.exists(k) for k in keys)
    photos.delete_photo(media, "gone", fields["photo_key"])
    photos.delete_photo(media, "gone", None)


def test_preview_size(media):
    buf = BytesIO()
    gradient(800, 1200).save(buf, format="JPEG")
    photos.set_photo(media, "prev", buf.getvalue())
    im = Image.open(BytesIO(photos.preview(media, "originals/prev.jpg", 0.3)))
    assert im.format == "JPEG" and im.size == (600, 337)
    im = Image.open(BytesIO(photos.preview(media, "originals/prev.jpg", 0.3, width=300)))
    assert im.size == (300, 168)


def test_heic_input(media):
    buf = BytesIO()
    pillow_heif.from_pillow(gradient(640, 480)).save(buf, format="HEIF")
    fields = photos.set_photo(media, "heic", buf.getvalue())
    assert (fields["photo_width"], fields["photo_height"]) == (640, 480)
    assert Image.open(BytesIO(media.get("originals/heic.jpg"))).format == "JPEG"
    assert media.exists("img/thumb/heic.webp")


def test_garbage_raises(media):
    with pytest.raises(PhotoError):
        photos.set_photo(media, "bad", b"not an image")
    with pytest.raises(PhotoError):
        photos.store_original(media, "bad", b"")
    assert media.listing() == {}


def test_variant_paths_match_keys():
    assert [p.format(slug="x") for p in photos.VARIANT_PATHS] == ["/" + k for k in photos.variant_keys("x")]
