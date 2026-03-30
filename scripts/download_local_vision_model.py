from __future__ import annotations

from pathlib import Path

from huggingface_hub import snapshot_download

from app.config import Settings


def main() -> None:
    settings = Settings()
    target_dir = settings.local_vision_model_dir.resolve()
    target_dir.parent.mkdir(parents=True, exist_ok=True)

    print(f"repo_id={settings.local_vision_model_id}")
    print(f"target_dir={target_dir}")
    resolved_path = snapshot_download(
        repo_id=settings.local_vision_model_id,
        local_dir=target_dir,
        max_workers=8,
    )
    print(f"downloaded_to={Path(resolved_path).resolve()}")


if __name__ == "__main__":
    main()
