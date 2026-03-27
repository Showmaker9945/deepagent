from app.config import Settings
from app.schemas import ClassificationResult, RunCreateRequest, RunImage
from app.visual import VisualAnalyzer, visual_report_status


def test_visual_analyzer_returns_config_issue_when_dashscope_key_is_placeholder(tmp_path):
    analyzer = VisualAnalyzer(Settings(DASHSCOPE_API_KEY="your-dashscope-api-key"))
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
    assert "占位值" in report.uncertainties[0]
    assert visual_report_status(report) == "degraded"
