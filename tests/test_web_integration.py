"""Independent HTTP-level acceptance of uploaded data, real events and safe downloads."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx

from office_agents.agent_runtime import AgentSession
from office_agents.config import Settings
from office_agents.web_runtime import RunController
from office_agents.web_schemas import SAMPLE_ROOT, UploadBlob, WebRunOptions
from office_agents.web_uploads import prepare_input
from office_agents.workflow_examples import workflow_mock_response

REQUEST = "生成研发部2026年第二季度工作报告"


def factory(handler):
    def create(options):
        return AgentSession(
            Settings(base_url="https://mock.invalid", model="web-acceptance", api_key="PRIVATE"),
            mode="offline_mock",
            max_requests=options.max_requests,
            max_total_output_tokens=options.max_output_tokens,
            retry_budget=options.retry_budget,
            transport=httpx.MockTransport(handler),
            sleep=lambda _: None,
        )

    return create


def test_uploaded_change_survives_same_graph_and_final_download(tmp_path):
    blobs = [
        UploadBlob(p.name, p.read_bytes())
        for p in sorted(SAMPLE_ROOT.iterdir())
        if p.suffix in {".csv", ".txt"}
    ]
    uploaded = [
        UploadBlob(b.name, b.content.replace(b"2026-06-30,active,75", b"2026-06-30,completed,100"))
        if b.name == "projects.csv"
        else b
        for b in blobs
    ]
    prepared = prepare_input(uploaded)
    changed_hash = hashlib.sha256(
        next(b.content for b in uploaded if b.name == "projects.csv")
    ).hexdigest()
    controller = RunController()
    assert controller.start(prepared, WebRunOptions(request=REQUEST), output_root=tmp_path)
    controller.wait(timeout=20)
    snapshot = controller.snapshot()
    assert snapshot.status == "completed" and snapshot.result.data_origin == "provided"
    assert [m.value for m in snapshot.result.metrics] == [3, 3, 1.0, 2]
    source = next(s for s in snapshot.result.sources if s.source_id == "projects.csv")
    assert source.sha256 == changed_hash
    final = next(d for d in snapshot.downloads if d.name == "report.md")
    assert final.data == (snapshot.artifact_dir / "report.md").read_bytes()
    assert "用户提供数据" in final.data.decode()
    assert "完成项目数 = 3" in final.data.decode()
    assert [e.model_dump() for e in snapshot.events] == [
        e.model_dump() for e in snapshot.result.events
    ]
    # Changing a widget or pressing the old submit again must not admit a second run.
    assert not controller.start(
        prepare_input(use_samples=True), WebRunOptions(request=REQUEST), output_root=tmp_path
    )
    assert controller.submission_count == 1
    assert len(list(tmp_path.iterdir())) == 1


def test_active_http_and_parallel_clicks_are_one_job_with_actual_start(tmp_path):
    entered, release = Event(), Event()
    calls = []

    def handler(request):
        role = json.loads(request.content)["messages"][0]["content"].splitlines()[0]
        calls.append(role)
        if len(calls) == 1:
            entered.set()
            assert release.wait(10)
        return workflow_mock_response(request)

    controller = RunController()
    prepared = prepare_input(use_samples=True)
    options = WebRunOptions(request=REQUEST)
    try:
        assert controller.start(
            prepared, options, output_root=tmp_path, session_factory=factory(handler)
        )
        assert entered.wait(5)
        running = controller.snapshot()
        assert running.status == "running"
        assert running.events[-1].event_type == "node_started"
        assert running.events[-1].role == "manager"
        assert not controller.reset()
        with ThreadPoolExecutor(max_workers=8) as pool:
            accepted = list(
                pool.map(
                    lambda _: controller.start(prepared, options, output_root=tmp_path), range(16)
                )
            )
        assert not any(accepted) and len(calls) == 1
    finally:
        release.set()
        controller.wait(timeout=20)
    finished = controller.snapshot()
    assert finished.status == "completed" and len(calls) == 6
    assert controller.submission_count == 1
    assert not controller.start(prepared, options, output_root=tmp_path)


def test_provider_error_fails_safe_without_final_download(tmp_path):
    controller = RunController()

    def error_handler(request):
        return httpx.Response(401, json={"error": "PRIVATE_PROVIDER_BODY_AND_API_KEY"})

    assert controller.start(
        prepare_input(use_samples=True),
        WebRunOptions(request=REQUEST),
        output_root=tmp_path,
        session_factory=factory(error_handler),
    )
    controller.wait(timeout=20)
    snapshot = controller.snapshot()
    assert snapshot.status == "failed" and snapshot.result.request_count == 1
    assert not any(d.name == "report.md" for d in snapshot.downloads)
    assert not (snapshot.artifact_dir / "report.md").exists()
    assert "PRIVATE" not in snapshot.result.model_dump_json()
    assert "PRIVATE" not in (snapshot.error or "")


def test_independent_sessions_do_not_share_results_or_inputs(tmp_path):
    controllers = [RunController(), RunController()]
    prepared = prepare_input(use_samples=True)
    for c, department in zip(controllers, ["研发部", "市场部"], strict=True):
        assert c.start(
            prepared,
            WebRunOptions(request=f"生成{department}2026年第二季度工作报告"),
            output_root=tmp_path,
        )
    for c in controllers:
        c.wait(timeout=20)
    left, right = [c.snapshot() for c in controllers]
    assert left.status == right.status == "completed" and left.run_id != right.run_id
    assert [m.value for m in left.result.metrics] == [3, 2, 2 / 3, 2]
    assert [m.value for m in right.result.metrics] == [1, 0, 0, 1]
    assert left.artifact_dir != right.artifact_dir
    left.result.metrics[0].value = 999
    assert controllers[0].snapshot().result.metrics[0].value == 3
    assert controllers[1].snapshot().result.metrics[0].value == 1
