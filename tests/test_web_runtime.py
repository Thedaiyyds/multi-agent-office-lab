"""Actual graph, admission races, event snapshots and safe download boundaries."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import httpx
import pytest

import office_agents.web_runtime as runtime
from office_agents.agent_runtime import AgentSession
from office_agents.config import Settings
from office_agents.web_schemas import PreparedInput, UploadBlob, WebRunOptions
from office_agents.web_uploads import WebInputError, prepare_input
from office_agents.workflow_examples import workflow_mock_response

REQUEST = "生成研发部2026年第二季度工作报告"


def options(**overrides):
    return WebRunOptions(**{"request": REQUEST, **overrides})


def factory(handler=workflow_mock_response, sessions=None):
    def create(opts):
        session = AgentSession(
            Settings(base_url="https://mock.invalid", model="web-fixture"),
            mode="offline_mock",
            transport=httpx.MockTransport(handler),
            max_requests=opts.max_requests,
            max_total_output_tokens=opts.max_output_tokens,
            retry_budget=opts.retry_budget,
            sleep=lambda _: None,
        )
        if sessions is not None:
            sessions.append(session)
        return session

    return create


def run(tmp_path, **overrides):
    controller = runtime.RunController()
    assert controller.start(
        prepare_input(use_samples=True), options(**overrides), output_root=tmp_path
    )
    snapshot = controller.wait()
    assert snapshot is not None and snapshot.status not in {"queued", "running"}
    return controller, snapshot


def test_real_mock_graph_without_environment_and_safe_downloads(tmp_path, monkeypatch):
    def no_environment():
        raise AssertionError("Mock must not read secrets.")

    monkeypatch.setattr(runtime.Settings, "from_env", no_environment)
    controller, snapshot = run(tmp_path)
    assert snapshot.status == "completed"
    assert snapshot.result.request_count == 6
    assert snapshot.result.usage["total_tokens"] is None
    assert snapshot.result.run_id == snapshot.run_id
    assert snapshot.result.data_origin == "simulated"
    assert snapshot.events == tuple(snapshot.result.events)
    artifacts = {download.name: download for download in snapshot.downloads}
    assert {"report.md", "draft.md", "run.json", "events.jsonl"} <= artifacts.keys()
    assert artifacts["report.md"].data == (snapshot.artifact_dir / "report.md").read_bytes()
    assert "离线模拟模型" in artifacts["report.md"].data.decode()
    # Downloads retain admitted bytes even if a local output file later changes.
    (snapshot.artifact_dir / "report.md").write_text("changed", encoding="utf-8")
    assert controller.snapshot().downloads == snapshot.downloads
    assert controller.submission_count == 1


def test_snapshot_deeply_isolated_and_terminal_requires_explicit_reset(tmp_path):
    controller, original = run(tmp_path)
    modified = controller.snapshot()
    modified.events[0].summary = "tampered"
    modified.result.nodes[0].input["user_text"] = "tampered"
    modified.result.metrics.clear()
    assert controller.snapshot() == original
    assert not controller.start(prepare_input(use_samples=True), options(), output_root=tmp_path)
    assert controller.submission_count == 1
    assert controller.reset()
    assert controller.snapshot() is None
    assert controller.start(prepare_input(use_samples=True), options(), output_root=tmp_path)
    second = controller.wait()
    assert second.status == "completed"
    assert second.run_id != original.run_id
    assert second.artifact_dir != original.artifact_dir
    assert controller.submission_count == 2


def test_concurrent_admission_progress_reset_and_options_freeze(tmp_path):
    reached, release = Event(), Event()
    sessions = []

    def handler(request):
        reached.set()
        assert release.wait(10)
        return workflow_mock_response(request)

    controller = runtime.RunController()
    admitted_options = options()
    prepared = prepare_input(use_samples=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(
            pool.map(
                lambda _: controller.start(
                    prepared,
                    admitted_options,
                    output_root=tmp_path,
                    session_factory=factory(handler, sessions),
                ),
                range(8),
            )
        )
    assert outcomes.count(True) == 1
    assert reached.wait(10)
    pending = controller.snapshot()
    assert pending.status == "running"
    assert pending.events[0].role == "manager"
    assert pending.events[0].event_type == "node_started"
    assert not controller.reset()
    assert controller.submission_count == 1
    admitted_options.request = "later widget edit"
    admitted_options.max_requests = 1
    pending.events[0].summary = "untrusted snapshot edit"
    assert controller.snapshot().events[0].summary != pending.events[0].summary
    release.set()
    final = controller.wait()
    assert final.status == "completed"
    assert final.result.user_text == REQUEST
    assert len(sessions) == 1 and sessions[0].request_count == 6


def test_input_directory_is_isolated_frozen_and_cleaned(tmp_path, monkeypatch):
    seen = []
    original = runtime.run_workflow

    def observed(text, data_root, session, **kwargs):
        seen.append(Path(data_root))
        assert Path(data_root).parent != tmp_path
        assert sorted(path.name for path in Path(data_root).iterdir()) == [
            "achievements.csv",
            "issues.txt",
            "projects.csv",
        ]
        return original(text, data_root, session, **kwargs)

    monkeypatch.setattr(runtime, "run_workflow", observed)
    _, snapshot = run(tmp_path)
    assert snapshot.status == "completed"
    assert len(seen) == 1 and not seen[0].exists()


def test_independent_sessions_keep_uploaded_statistics_and_outputs_separate(tmp_path):
    samples = prepare_input(use_samples=True)
    uploaded = prepare_input(
        UploadBlob(
            blob.name,
            blob.content.replace(b"2026-06-30,active,75", b"2026-06-30,completed,100")
            if blob.name == "projects.csv"
            else blob.content,
        )
        for blob in samples.files
    )
    controllers = [runtime.RunController(), runtime.RunController()]
    for controller, prepared in zip(controllers, [samples, uploaded], strict=True):
        assert controller.start(prepared, options(), output_root=tmp_path)
    sample_result, uploaded_result = [controller.wait() for controller in controllers]
    assert sample_result.status == uploaded_result.status == "completed"
    assert sample_result.run_id != uploaded_result.run_id
    assert sample_result.artifact_dir != uploaded_result.artifact_dir
    assert sample_result.result.data_origin == "simulated"
    assert uploaded_result.result.data_origin == "provided"
    original_metrics = {metric.metric_id: metric.value for metric in sample_result.result.metrics}
    uploaded_metrics = {metric.metric_id: metric.value for metric in uploaded_result.result.metrics}
    assert original_metrics["completed_project_count"] == 2
    assert uploaded_metrics["completed_project_count"] == 3
    assert original_metrics["completion_rate"] != uploaded_metrics["completion_rate"]
    original_hashes = {source.source_id: source.sha256 for source in sample_result.result.sources}
    uploaded_hashes = {source.source_id: source.sha256 for source in uploaded_result.result.sources}
    assert original_hashes["projects.csv"] != uploaded_hashes["projects.csv"]
    assert original_hashes["achievements.csv"] == uploaded_hashes["achievements.csv"]


def test_failed_workflow_cleans_isolated_input_directory(tmp_path, monkeypatch):
    seen = []

    def failed(text, data_root, session, **kwargs):
        seen.append(Path(data_root))
        assert (Path(data_root) / "projects.csv").is_file()
        raise RuntimeError("PRIVATE_SECRET_FAILURE")

    monkeypatch.setattr(runtime, "run_workflow", failed)
    _, snapshot = run(tmp_path)
    assert snapshot.status == "failed"
    assert len(seen) == 1 and not seen[0].exists()
    assert "PRIVATE_SECRET_FAILURE" not in repr(snapshot)


@pytest.mark.parametrize("scenario", ["bad-fact", "missing-section"])
def test_revision_downloads_use_real_feedback_and_corrected_fact(tmp_path, scenario):
    _, snapshot = run(tmp_path, test_scenario=scenario)
    assert snapshot.status == "completed"
    assert snapshot.result.revision_count == 1
    assert snapshot.result.request_count == 7
    assert not snapshot.result.revision_history[0].review.passed
    assert snapshot.result.revision_history[1].review.passed
    assert {"revisions/00/draft.md", "revisions/01/draft.md", "report.md"} <= {
        artifact.name for artifact in snapshot.downloads
    }


def test_revision_limit_provides_draft_but_never_final(tmp_path):
    _, snapshot = run(tmp_path, test_scenario="always-bad", max_revisions=1)
    assert snapshot.status == "review_failed"
    assert snapshot.result.request_count == 6
    assert "draft.md" in {artifact.name for artifact in snapshot.downloads}
    assert "report.md" not in {artifact.name for artifact in snapshot.downloads}
    assert not (snapshot.artifact_dir / "report.md").exists()


@pytest.mark.parametrize(
    ("overrides", "requests", "reserved"),
    [({"max_requests": 2}, 2, 640), ({"max_output_tokens": 256}, 1, 256)],
)
def test_api_and_output_budget_stops_before_extra_http(tmp_path, overrides, requests, reserved):
    _, snapshot = run(tmp_path, **overrides)
    assert snapshot.status == "failed"
    assert snapshot.result.request_count == requests
    assert snapshot.result.reserved_output_tokens == reserved
    assert "report.md" not in {artifact.name for artifact in snapshot.downloads}


def test_needs_input_has_no_writer_or_final(tmp_path):
    _, snapshot = run(tmp_path, request="请生成报告")
    assert snapshot.status == "needs_input"
    assert snapshot.result.request_count == 1
    assert [node.role for node in snapshot.result.nodes] == ["manager"]
    assert "report.md" not in {artifact.name for artifact in snapshot.downloads}


def test_retry_budget_is_independent_from_revisions(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ReadTimeout("PRIVATE_PROVIDER_BODY", request=request)
        return workflow_mock_response(request)

    controller = runtime.RunController()
    assert controller.start(
        prepare_input(use_samples=True),
        options(retry_budget=1),
        output_root=tmp_path,
        session_factory=factory(handler),
    )
    snapshot = controller.wait()
    assert snapshot.status == "completed"
    assert len(calls) == snapshot.result.request_count == 7
    assert snapshot.result.retry_count == 1
    assert snapshot.result.revision_count == 0
    assert "PRIVATE_PROVIDER_BODY" not in repr(snapshot)


@pytest.mark.parametrize("stage", ["session", "export"])
def test_unexpected_secret_errors_are_static_and_no_final_download(tmp_path, monkeypatch, stage):
    def failed(*args):
        raise RuntimeError("PRIVATE_SECRET_KEY_AND_PROVIDER_BODY")

    controller = runtime.RunController()
    if stage == "export":
        monkeypatch.setattr(runtime, "save_workflow", failed)
    assert controller.start(
        prepare_input(use_samples=True),
        options(),
        output_root=tmp_path,
        session_factory=failed if stage == "session" else factory(),
    )
    snapshot = controller.wait()
    assert snapshot.status == "failed"
    assert not snapshot.downloads
    assert "PRIVATE_SECRET_KEY_AND_PROVIDER_BODY" not in repr(snapshot)


def test_direct_invalid_prepared_input_cannot_bypass_upload_validation(tmp_path):
    controller = runtime.RunController()
    hostile = PreparedInput(files=(UploadBlob("../secret.csv", b"secret"),), data_origin="provided")
    with pytest.raises(WebInputError):
        controller.start(hostile, options(), output_root=tmp_path)
    assert controller.submission_count == 0
    assert controller.snapshot() is None


def test_mutated_invalid_options_have_safe_validation_error_and_no_worker(tmp_path):
    controller = runtime.RunController()
    hostile = options()
    hostile.mode = "PRIVATE_SECRET_BAD_MODE"
    with pytest.raises(runtime.WebRunError) as raised:
        controller.start(prepare_input(use_samples=True), hostile, output_root=tmp_path)
    assert "PRIVATE_SECRET_BAD_MODE" not in str(raised.value)
    assert controller.submission_count == 0


def test_thread_start_failure_is_terminal_resettable_and_safe(tmp_path, monkeypatch):
    def failed(thread):
        raise RuntimeError("PRIVATE_SECRET_THREAD_ERROR")

    monkeypatch.setattr(runtime.Thread, "start", failed)
    controller = runtime.RunController()
    assert controller.start(prepare_input(use_samples=True), options(), output_root=tmp_path)
    snapshot = controller.wait()
    assert snapshot.status == "failed"
    assert "PRIVATE_SECRET_THREAD_ERROR" not in repr(snapshot)
    assert controller.reset()
