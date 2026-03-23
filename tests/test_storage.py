from app.schemas import RunCreateRequest, VisualReport
from app.storage import Storage


def test_storage_init_creates_query_indexes(tmp_path):
    storage = Storage(tmp_path / "storage.db")
    storage.init_db()

    with storage.connect() as connection:
        runs_indexes = {row["name"] for row in connection.execute("PRAGMA index_list(runs)").fetchall()}
        event_indexes = {row["name"] for row in connection.execute("PRAGMA index_list(run_events)").fetchall()}
        source_indexes = {row["name"] for row in connection.execute("PRAGMA index_list(run_sources)").fetchall()}
        feedback_indexes = {row["name"] for row in connection.execute("PRAGMA index_list(feedback)").fetchall()}

    assert "idx_runs_status_updated_at" in runs_indexes
    assert "idx_run_events_run_id_id" in event_indexes
    assert "idx_run_sources_run_id_id" in source_indexes
    assert "idx_feedback_run_id_created_at" in feedback_indexes


def test_storage_check_ready_returns_true_for_initialized_db(tmp_path):
    storage = Storage(tmp_path / "ready.db")
    storage.init_db()

    ready, error = storage.check_ready()

    assert ready is True
    assert error is None


def test_storage_links_uploaded_images_and_persists_visual_report(tmp_path):
    storage = Storage(tmp_path / "visual.db")
    storage.init_db()
    image = storage.create_image_upload(
        image_id="img-1",
        file_name="ticket.png",
        mime_type="image/png",
        local_path=str(tmp_path / "ticket.png"),
        size_bytes=256,
    )

    run_id = storage.create_run(
        RunCreateRequest(question="这个演出要不要去？", image_ids=[image.id]),
        "local-user",
    )
    report = VisualReport(
        summary="图片里能看到时间、场馆和票价。",
        extracted_facts=["时间是周日 20:00", "票价 280 元"],
        uncertainties=["没看到退票规则"],
        image_count=1,
    )
    storage.update_status(run_id, "running", visual_report=report)

    run = storage.get_run(run_id)
    images = storage.list_images(run_id)

    assert run is not None
    assert run.visual_report is not None
    assert run.visual_report.summary == "图片里能看到时间、场馆和票价。"
    assert len(images) == 1
    assert images[0].id == "img-1"
    assert images[0].run_id == run_id
