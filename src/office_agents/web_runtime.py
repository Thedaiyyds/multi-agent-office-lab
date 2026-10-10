"""One bounded background workflow per browser session; no UI calls in workers."""

import copy
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock, Thread
from uuid import uuid4

from office_agents.agent_runtime import AgentSession
from office_agents.config import Settings
from office_agents.web_schemas import (
    WEB_OUTPUT_ROOT,
    DownloadArtifact,
    JobSnapshot,
    PreparedInput,
    WebRunOptions,
)
from office_agents.web_uploads import validate_prepared, write_prepared
from office_agents.workflow import run_workflow
from office_agents.workflow_examples import make_workflow_mock_transport
from office_agents.workflow_export import save_workflow
from office_agents.workflow_schemas import WorkflowEvent


class WebRunError(ValueError):
    """Safe input/configuration error without the original validation payload."""


def _make_session(options: WebRunOptions) -> AgentSession:
    settings = (
        Settings(base_url="https://mock.invalid", model="scripted-workflow")
        if options.mode == "mock"
        else Settings.from_env()
    )
    settings = Settings.model_validate(
        {**settings.model_dump(), "timeout_seconds": options.timeout_seconds}
    )
    return AgentSession(
        settings,
        mode="offline_mock" if options.mode == "mock" else "live",
        profile="deepseek",
        max_requests=options.max_requests,
        max_total_output_tokens=options.max_output_tokens,
        retry_budget=options.retry_budget,
        transport=make_workflow_mock_transport() if options.mode == "mock" else None,
    )


def _downloads(directory: Path, completed: bool) -> tuple[DownloadArtifact, ...]:
    # Only files written by save_workflow are eligible; no request-supplied paths.
    names = ["run.json", "events.jsonl", "draft.md"]
    if completed:
        names.append("report.md")
    files = [(name, directory / name) for name in names]
    for revision_index in range(3):
        for name in ("draft.md", "review.json"):
            relative = f"revisions/{revision_index:02d}/{name}"
            files.append((relative, directory / relative))
    return tuple(
        DownloadArtifact(
            name=name,
            data=path.read_bytes(),
            mime="application/json" if name.endswith(".json") else "text/plain",
        )
        for name, path in files
        if path.is_file()
    )


class RunController:
    """Admission is once per controller until an explicit terminal-state reset.

    This guards Streamlit reruns in one session, not process restarts or different
    browser sessions. A reset cannot cancel a worker or refund an HTTP budget.
    """

    def __init__(self):
        self._lock = Lock()
        self._job: JobSnapshot | None = None
        self._thread: Thread | None = None
        self._submission_count = 0

    @property
    def submission_count(self) -> int:
        with self._lock:
            return self._submission_count

    def snapshot(self) -> JobSnapshot | None:
        with self._lock:
            return copy.deepcopy(self._job)

    def reset(self) -> bool:
        with self._lock:
            if (self._job is not None and self._job.status in {"queued", "running"}) or (
                self._thread is not None and self._thread.is_alive()
            ):
                return False
            self._job = None
            self._thread = None
            return True

    def wait(self, timeout: float = 30) -> JobSnapshot | None:
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
        return self.snapshot()

    def start(
        self,
        prepared: PreparedInput,
        options: WebRunOptions,
        *,
        output_root: Path = WEB_OUTPUT_ROOT,
        session_factory: Callable[[WebRunOptions], AgentSession] | None = None,
    ) -> bool:
        with self._lock:
            if self._job is not None:
                return False
            # Contracts permit mutation after construction; revalidate and copy at
            # admission so later widget changes cannot alter the admitted run.
            try:
                frozen_options = WebRunOptions.model_validate(options.model_dump()).model_copy(
                    deep=True
                )
                frozen_root = Path(output_root)
            except (ValueError, TypeError, AttributeError):
                raise WebRunError("运行选项无效，请检查需求、预算和超时设置。") from None
            frozen_input = validate_prepared(prepared)
            run_id = str(uuid4())
            self._job = JobSnapshot(run_id=run_id, status="queued")
            self._submission_count += 1
            self._thread = Thread(
                target=self._work,
                args=(frozen_input, frozen_options, frozen_root, session_factory),
                name=f"office-workflow-{run_id}",
                daemon=True,
            )
            try:
                self._thread.start()
            except Exception:
                self._thread = None
                self._job = JobSnapshot(
                    run_id=run_id, status="failed", error="后台任务无法启动，请新建任务后重试。"
                )
            return True

    def _event(self, event: WorkflowEvent) -> None:
        with self._lock:
            if self._job is not None:
                self._job = JobSnapshot(
                    run_id=self._job.run_id,
                    status="running",
                    events=(*self._job.events, event.model_copy(deep=True)),
                )

    def _work(self, prepared, options, output_root, session_factory):
        session = None
        result = None
        artifact_dir = None
        with self._lock:
            run_id = self._job.run_id
            self._job = JobSnapshot(run_id=run_id, status="running")
        try:
            with TemporaryDirectory(prefix="office-web-input-") as temporary:
                data_root = Path(temporary)
                write_prepared(prepared, data_root)
                session = (session_factory or _make_session)(options)
                if (
                    not isinstance(session, AgentSession)
                    or session.mode != ("offline_mock" if options.mode == "mock" else "live")
                    or session.max_requests != options.max_requests
                    or session.max_total_output_tokens != options.max_output_tokens
                    or session.retry_budget != options.retry_budget
                    or session.request_count != 0
                ):
                    raise WebRunError("模型会话设置未满足运行预算。")
                result = run_workflow(
                    options.request,
                    data_root,
                    session,
                    data_origin=prepared.data_origin,
                    run_id=run_id,
                    max_revisions=options.max_revisions,
                    test_scenario=options.test_scenario,
                    on_event=self._event,
                )
                session.close()
                session = None
                # A completed graph is still provisional until final export gate
                # succeeds. No report bytes can escape on a gate/save failure.
                artifact_dir = save_workflow(result, output_root)
                downloads = _downloads(artifact_dir, result.status == "completed")
            with self._lock:
                self._job = JobSnapshot(
                    run_id=run_id,
                    status=result.status,
                    events=tuple(event.model_copy(deep=True) for event in result.events),
                    result=result.model_copy(deep=True),
                    error=result.error,
                    artifact_dir=artifact_dir,
                    downloads=downloads,
                )
        except Exception:
            with self._lock:
                self._job = JobSnapshot(
                    run_id=run_id,
                    status="failed",
                    events=copy.deepcopy(self._job.events),
                    result=result.model_copy(deep=True) if result is not None else None,
                    artifact_dir=artifact_dir,
                    error="任务执行或导出失败；未提供最终报告，请检查本地配置与输入。",
                )
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass
