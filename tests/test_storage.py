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
