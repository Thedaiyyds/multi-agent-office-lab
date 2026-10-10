"""UI acceptance using real session controllers and the offline HTTP graph."""

from importlib import import_module
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from office_agents import web_ui
from office_agents.config import Settings
from office_agents.web_runtime import RunController
from office_agents.web_schemas import SAMPLE_ROOT

APP = Path(__file__).resolve().parents[1] / "app.py"


@pytest.fixture(scope="module")
def rendering_dependencies():
    # Streamlit's arrow.dataframe lazily imports these on the first result render.
    # Initialize third-party native/compiled dependencies on the pytest thread,
    # outside AppTest's script-completion timeout. The app still renders actual
    # dataframes and executes the unchanged graph; this is not a mocked renderer.
    import_module("pandas")
    import_module("pyarrow")


@pytest.fixture
def app(tmp_path, monkeypatch, rendering_dependencies):
    class LocalController(RunController):
        def start(self, *args, **kwargs):
            kwargs["output_root"] = tmp_path
            return super().start(*args, **kwargs)

    monkeypatch.setattr(web_ui, "RunController", LocalController)
    instance = AppTest.from_file(str(APP), default_timeout=20).run()
    yield instance
    # Join a worker even if a UI assertion fails, before monkeypatch restores its
    # factory. Tests must not leave a task running into the next browser session.
    instance.session_state["office_run_controller"].wait(timeout=20)


def widget(elements, label):
    return next(element for element in elements if element.label == label)


def submit(app):
    widget(app.button, "开始协作").click().run()
    controller = app.session_state["office_run_controller"]
    snapshot = controller.wait(timeout=20)
    app.run()
    assert not app.exception
    return controller, snapshot


def downloads(app):
    return [item.label for item in app.get("download_button")]


def test_defaults_do_not_start_or_load_env_and_reruns_do_not_duplicate(app, monkeypatch):
    def forbid_env(*args, **kwargs):
        pytest.fail("Default mock must not read local model credentials")

    monkeypatch.setattr(Settings, "from_env", forbid_env)
    controller = app.session_state["office_run_controller"]
    assert controller.submission_count == 0
    assert widget(app.radio, "模型模式").value == "离线模拟"
    assert widget(app.number_input, "网络重试预算").value == 0
    assert widget(app.number_input, "HTTP请求上限").value == 10
    controller, snapshot = submit(app)
    assert snapshot.status == "completed"
    assert snapshot.result.request_count == 6
    assert controller.submission_count == 1
    assert [(metric.label, metric.value) for metric in app.metric] == [
        ("项目数", "3"),
        ("已完成项目数", "2"),
        ("项目完成率", "66.7%"),
        ("成果数", "2"),
    ]
    assert "下载最终报告" in downloads(app)
    for _ in range(3):
        app.run()
    assert controller.submission_count == 1
    assert controller.snapshot().run_id == snapshot.run_id
    assert widget(app.button, "开始协作").disabled
    assert any("不代表项目开发完成率" in item.value for item in app.caption)


def test_needs_input_stops_before_data_and_has_no_final_download(app):
    widget(app.text_area, "报告需求").set_value("请写一份报告")
    _, snapshot = submit(app)
    assert snapshot.status == "needs_input"
    assert snapshot.result.request_count == 1
    assert "下载最终报告" not in downloads(app)
    assert any("需要补充输入" in item.value for item in app.markdown)


def test_missing_uploads_block_before_admission(app):
    widget(app.radio, "数据来源").set_value("上传我的文件")
    widget(app.button, "开始协作").click().run()
    assert not app.exception
    assert app.session_state["office_run_controller"].submission_count == 0
    assert app.error
    assert len(app.session_state["office_input_issues"]) == 3
    assert not downloads(app)


def test_empty_requirement_error_is_safe_and_clears_old_upload_issues(app):
    widget(app.radio, "数据来源").set_value("上传我的文件")
    widget(app.button, "开始协作").click().run()
    assert app.session_state["office_input_issues"]
    widget(app.radio, "数据来源").set_value("实验样例")
    widget(app.text_area, "报告需求").set_value("")
    widget(app.button, "开始协作").click().run()
    assert not app.exception
    assert app.session_state["office_run_controller"].submission_count == 0
    assert not app.session_state.get("office_input_issues")
    assert any("输入或预算无效" in error.value for error in app.error)


@pytest.mark.parametrize("scenario", ["错误事实", "缺失章节"])
def test_explicit_fault_is_revised_and_all_rounds_visible(app, scenario):
    widget(app.checkbox, "启用故意注入错误的实验").check()
    widget(app.selectbox, "注入场景").set_value(scenario)
    _, snapshot = submit(app)
    assert snapshot.status == "completed"
    assert snapshot.result.revision_count == 1
    assert snapshot.result.request_count == 7
    assert [record.review.passed for record in snapshot.result.revision_history] == [False, True]
    assert any("主动注入" in item.value for item in app.warning)
    assert "下载最终报告" in downloads(app)
    assert any("第 0 轮草稿" in item.label for item in app.expander)
    assert any("第 1 轮草稿" in item.label for item in app.expander)


def test_persistent_fault_stops_at_limit_without_final_download(app):
    widget(app.checkbox, "启用故意注入错误的实验").check()
    widget(app.selectbox, "注入场景").set_value("持续错误")
    widget(app.number_input, "最多返工次数").set_value(1)
    _, snapshot = submit(app)
    assert snapshot.status == "review_failed"
    assert snapshot.result.revision_count == 1
    assert len(snapshot.result.revision_history) == 2
    assert "下载最终报告" not in downloads(app)
    assert any("审核未通过" in item.value for item in app.markdown)


def test_request_limit_preserves_failure_and_no_final_download(app):
    widget(app.number_input, "HTTP请求上限").set_value(4)
    _, snapshot = submit(app)
    assert snapshot.status == "failed"
    assert snapshot.result.request_count == 4
    assert "下载最终报告" not in downloads(app)
    assert app.error


def test_new_task_explicitly_resets_retained_result(app):
    controller, first = submit(app)
    widget(app.button, "新建任务").click().run()
    assert controller.snapshot() is None
    assert widget(app.button, "开始协作").disabled is False
    _, second = submit(app)
    assert second.status == "completed"
    assert second.run_id != first.run_id
    assert controller.submission_count == 2


def test_browser_sessions_have_independent_controllers(app):
    other = AppTest.from_file(str(APP), default_timeout=20).run()
    controller, first = submit(app)
    second_controller = other.session_state["office_run_controller"]
    assert second_controller is not controller
    assert second_controller.snapshot() is None
    assert second_controller.submission_count == 0
    assert first.status == "completed"


def test_uploaded_valid_files_change_statistics_in_ui(app, monkeypatch):
    class Uploaded:
        def __init__(self, name, content):
            self.name, self.content = name, content

        def getvalue(self):
            return self.content

    files = [
        Uploaded(path.name, path.read_bytes())
        for path in (
            SAMPLE_ROOT / name for name in ("projects.csv", "achievements.csv", "issues.txt")
        )
    ]
    project = next(file for file in files if file.name == "projects.csv")
    lines = project.content.decode().splitlines()
    # Keep one source record for the requested department/date, not UI-generated metrics.
    matching = next(line for line in lines[1:] if "研发部" in line and "2026-06" in line)
    project.content = (lines[0] + "\n" + matching + "\n").encode()
    monkeypatch.setattr(web_ui.st, "file_uploader", lambda *args, **kwargs: files)
    widget(app.radio, "数据来源").set_value("上传我的文件")
    _, snapshot = submit(app)
    assert snapshot.status == "completed"
    assert snapshot.result.data_origin == "provided"
    assert (
        next(
            metric.value
            for metric in snapshot.result.metrics
            if metric.metric_id == "project_count"
        )
        == 1
    )
    assert widget(app.metric, "项目数").value == "1"


def test_active_task_freezes_form_and_terminal_poll_enables_new_task(app, monkeypatch):
    from threading import Event

    import httpx

    from office_agents import web_runtime
    from office_agents.agent_runtime import AgentSession
    from office_agents.workflow_examples import workflow_mock_response

    reached, release = Event(), Event()

    def handler(request):
        reached.set()
        assert release.wait(10)
        return workflow_mock_response(request)

    def factory(options):
        return AgentSession(
            Settings(base_url="https://mock.invalid", model="ui-delayed-fixture"),
            mode="offline_mock",
            max_requests=options.max_requests,
            max_total_output_tokens=options.max_output_tokens,
            retry_budget=options.retry_budget,
            transport=httpx.MockTransport(handler),
        )

    monkeypatch.setattr(web_runtime, "_make_session", factory)
    widget(app.button, "开始协作").click().run()
    assert reached.wait(5)
    controller = app.session_state["office_run_controller"]
    try:
        assert controller.snapshot().status == "running"
        assert widget(app.button, "开始协作").disabled
        assert widget(app.button, "新建任务").disabled
        assert widget(app.text_area, "报告需求").disabled
        assert controller.snapshot().events[0].event_type == "node_started"
        app.run()
        assert controller.submission_count == 1
        assert not controller.reset()
    finally:
        release.set()
        controller.wait(10)
    app.run()
    assert not app.exception
    assert not widget(app.button, "新建任务").disabled
    assert controller.submission_count == 1
    assert all(item.proto.ignore_rerun for item in app.get("download_button"))


def test_samples_selection_ignores_stale_uploaded_widget_bytes(app, monkeypatch):
    class Uploaded:
        name = "../private.csv"

        def getvalue(self):
            return b"PRIVATE_SHOULD_NOT_BE_READ"

    monkeypatch.setattr(web_ui.st, "file_uploader", lambda *args, **kwargs: [Uploaded()])
    controller, snapshot = submit(app)
    assert snapshot.status == "completed"
    assert snapshot.result.data_origin == "simulated"
    assert "PRIVATE_SHOULD_NOT_BE_READ" not in repr(snapshot)
    assert controller.submission_count == 1
