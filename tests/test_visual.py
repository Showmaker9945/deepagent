from app.config import Settings
from app.schemas import ClassificationResult, RunCreateRequest, RunImage
from app.visual import VisualAnalyzer, visual_report_status


def test_visual_analyzer_reports_missing_local_model_directory(tmp_path):
    analyzer = VisualAnalyzer(
        Settings(
            VISION_BACKEND="local_hf",
            LOCAL_VISION_MODEL_DIR=tmp_path / "missing-model",
        )
    )
    image_path = tmp_path / "poster.png"
    image_path.write_bytes(b"fake-image")

    report = analyzer.analyze(
        RunCreateRequest(question="这张图里的活动要不要去？"),
        ClassificationResult(category="travel", reason="stub"),
        [
            RunImage(
                id="img-1",
                run_id="run-1",
                file_name="poster.png",
                mime_type="image/png",
                local_path=str(image_path),
                size_bytes=image_path.stat().st_size,
                created_at="2026-03-27T00:00:00Z",
            )
        ],
    )

    assert report.image_count == 1
    assert report.extracted_facts == []
    assert "尚未下载完成" in report.uncertainties[0]
    assert visual_report_status(report) == "degraded"


def test_visual_analyzer_dashscope_backend_still_flags_placeholder_key(tmp_path):
    analyzer = VisualAnalyzer(
        Settings(
            VISION_BACKEND="dashscope",
            DASHSCOPE_API_KEY="your-dashscope-api-key",
        )
    )
    image_path = tmp_path / "poster.png"
    image_path.write_bytes(b"fake-image")

    report = analyzer.analyze(
        RunCreateRequest(question="这张图里的活动要不要去？"),
        ClassificationResult(category="travel", reason="stub"),
        [
            RunImage(
                id="img-1",
                run_id="run-1",
                file_name="poster.png",
                mime_type="image/png",
                local_path=str(image_path),
                size_bytes=image_path.stat().st_size,
                created_at="2026-03-27T00:00:00Z",
            )
        ],
    )

    assert "占位值" in report.uncertainties[0]
    assert visual_report_status(report) == "degraded"
