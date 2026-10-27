"""Photo handling: strip metadata, then store in S3-compatible object storage.

Photos from phones carry EXIF metadata: exact GPS position, device model, sometimes the
owner's name. We re-encode the pixels into a new JPEG, which drops all metadata, and only
the object key ever enters the event stream or the database.
"""

from __future__ import annotations

import io
import uuid
from functools import cache
from typing import TYPE_CHECKING

import boto3
from PIL import Image, ImageOps

from pomorie.config import get_settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

MAX_SIDE_PX = 1600
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class InvalidPhoto(ValueError):
    pass


def strip_metadata(data: bytes) -> bytes:
    """Return a metadata-free JPEG of the image, rotated upright and capped in size."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise InvalidPhoto("photo larger than 10 MB")
    try:
        with Image.open(io.BytesIO(data)) as source:
            upright = ImageOps.exif_transpose(source).convert("RGB")  # rotate before EXIF goes
            upright.thumbnail((MAX_SIDE_PX, MAX_SIDE_PX))
            clean = Image.new("RGB", upright.size)
            clean.paste(upright)  # copy pixels only; no info dict, EXIF, XMP or ICC carried over
    except (OSError, Image.DecompressionBombError) as exc:
        raise InvalidPhoto("not a readable image") from exc
    out = io.BytesIO()
    clean.save(out, format="JPEG", quality=85, optimize=True)
    return out.getvalue()


@cache
def s3_client() -> S3Client:
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name="us-east-1",
    )


def ensure_bucket() -> None:
    client, bucket = s3_client(), get_settings().s3_bucket
    existing = {b["Name"] for b in client.list_buckets().get("Buckets", [])}
    if bucket not in existing:
        client.create_bucket(Bucket=bucket)


def store_photo(event_id: uuid.UUID, data: bytes) -> str:
    key = f"photos/{event_id}/{uuid.uuid4().hex}.jpg"
    s3_client().put_object(
        Bucket=get_settings().s3_bucket,
        Key=key,
        Body=strip_metadata(data),
        ContentType="image/jpeg",
    )
    return key


def delete_photos(keys: list[str]) -> int:
    if not keys:
        return 0
    s3_client().delete_objects(
        Bucket=get_settings().s3_bucket, Delete={"Objects": [{"Key": k} for k in keys]}
    )
    return len(keys)
