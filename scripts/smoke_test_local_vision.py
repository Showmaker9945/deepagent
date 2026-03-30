from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.config import Settings
from app.schemas import ClassificationResult, RunCreateRequest, RunImage
from app.visual import VisualAnalyzer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke test the local HF vision model.")
    parser.add_argument("--image", required=True, help="Path to the local image file")
    parser.add_argument("--question", required=True, help="Decision question for the image")
    parser.add_argument("--category", default="travel", help="Decision category label")
    parser.add_argument("--notes", default="", help="Optional extra notes")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    image_path = Path(args.image).resolve()
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    settings = Settings(VISION_BACKEND="local_hf")
    analyzer = VisualAnalyzer(settings)
    report = analyzer.analyze(
        RunCreateRequest(question=args.question, notes=args.notes or None),
        ClassificationResult(category=args.category, reason="smoke-test"),
        [
            RunImage(
                id="smoke-image",
                run_id="smoke-run",
                file_name=image_path.name,
                mime_type=_guess_mime_type(image_path),
                local_path=str(image_path),
                size_bytes=image_path.stat().st_size,
                created_at="2026-03-28T00:00:00Z",
            )
        ],
    )
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))


def _guess_mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    return "image/png"


if __name__ == "__main__":
    main()
