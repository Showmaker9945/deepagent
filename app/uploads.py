from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path

from app.config import Settings
from app.schemas import RunImage
from app.storage import Storage

ALLOWED_IMAGE_MIME_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def persist_uploaded_image(
    settings: Settings,
    storage: Storage,
    *,
    file_name: str | None,
    mime_type: str | None,
    content: bytes,
) -> RunImage:
    normalized_mime = (mime_type or "").lower().strip()
    if normalized_mime not in ALLOWED_IMAGE_MIME_TYPES:
        allowed = ", ".join(sorted(ALLOWED_IMAGE_MIME_TYPES))
        raise ValueError(f"Unsupported image type. Allowed: {allowed}")

    if not content:
        raise ValueError("Uploaded image is empty.")
    if len(content) > settings.upload_max_image_bytes:
        raise ValueError(
            f"Image is too large. Max size is {settings.upload_max_image_bytes // 1_000_000} MB."
        )

    safe_name = normalize_upload_file_name(file_name)
    image_id = uuid.uuid4().hex
    suffix = choose_file_suffix(safe_name, normalized_mime)
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    local_path = settings.uploads_dir / f"{image_id}{suffix}"
    local_path.write_bytes(content)

    return storage.create_image_upload(
        image_id=image_id,
        file_name=safe_name,
        mime_type=normalized_mime,
        local_path=str(local_path),
        size_bytes=len(content),
    )


def normalize_upload_file_name(file_name: str | None) -> str:
    candidate = Path((file_name or "").strip()).name
    return candidate or "image"


def choose_file_suffix(file_name: str, mime_type: str) -> str:
    original_suffix = Path(file_name).suffix.lower()
    guessed_suffix = ALLOWED_IMAGE_MIME_TYPES[mime_type]
    if original_suffix and mimetypes.guess_type(f"file{original_suffix}")[0] == mime_type:
        return original_suffix
    return guessed_suffix
