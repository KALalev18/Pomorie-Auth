import io
import uuid

import pytest
from PIL import Image

from pomorie.api.app import ReportIn, build_event
from pomorie.contracts import REPORT_SUBMITTED, validate
from pomorie.photos import InvalidPhoto, strip_metadata
from pomorie.privacy import normalise_plate, plate_hash, pseudonym

GPS_IFD = 0x8825


def test_cyrillic_and_latin_plates_normalise_to_the_same_value() -> None:
    assert normalise_plate("А 1234 ВК") == normalise_plate("a1234bk") == "A1234BK"


def test_plate_hash_is_keyed() -> None:
    assert plate_hash("A1234BK", key="k1") == plate_hash("а 1234 вк", key="k1")
    assert plate_hash("A1234BK", key="k1") != plate_hash("A1234BK", key="k2")
    assert plate_hash("  -  ", key="k1") is None


def test_pseudonym_purposes_do_not_collide() -> None:
    assert pseudonym("x", "plate", key="k") != pseudonym("x", "reporter", key="k")


def _jpeg_with_gps() -> bytes:
    image = Image.new("RGB", (3000, 2000), "orange")
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"  # camera make
    exif.get_ifd(GPS_IFD)[2] = (42.0, 34.0, 6.0)  # GPS latitude
    out = io.BytesIO()
    image.save(out, format="JPEG", exif=exif)
    return out.getvalue()


def test_strip_metadata_removes_exif_and_downsizes() -> None:
    original = _jpeg_with_gps()
    with Image.open(io.BytesIO(original)) as before:
        assert before.getexif().get_ifd(GPS_IFD)

    cleaned = strip_metadata(original)
    with Image.open(io.BytesIO(cleaned)) as after:
        assert not after.getexif()
        assert "exif" not in after.info
        assert max(after.size) == 1600


def test_strip_metadata_rejects_non_images() -> None:
    with pytest.raises(InvalidPhoto):
        strip_metadata(b"definitely not a jpeg")


def test_api_events_satisfy_the_contract() -> None:
    report = ReportIn(
        reporter_id=uuid.uuid4(),
        category="illegal_parking",
        lat=42.5684,
        lon=27.6168,
        accuracy_m=6,
        description="Blocking the pavement",
        plate="СА 1234 ВК",
    )
    event = build_event(report, uuid.uuid4(), [f"photos/{uuid.uuid4()}/{'a' * 32}.jpg"], "web")
    assert validate(REPORT_SUBMITTED, event) == []
    assert "СА 1234" not in str(event)  # the raw plate never leaves the API


def test_unknown_category_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown category"):
        ReportIn(reporter_id=uuid.uuid4(), category="graffiti", lat=42.5, lon=27.6)
