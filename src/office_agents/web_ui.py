"""Chinese, session-isolated Streamlit interface to the existing workflow."""

import streamlit as st
from pydantic import ValidationError

from office_agents.web_runtime import RunController
from office_agents.web_schemas import JobSnapshot, UploadBlob, WebRunOptions
from office_agents.web_uploads import WebInputError, prepare_input

DEFAULT_REQUEST = (
    "生成研发部2026年第二季度工作报告。日期范围为2026-04-01（含）至"
    "2026-07-01（不含）；章节依次为工作概况、主要成果、问题与风险、后续计划。"
)
ROLES = {
    "manager": "需求经理",
    "planner": "规划助手",
    "data": "数据助手",
    "writer": "撰写助手",
    "checker": "审核助手",
}
STATUSES = {
    "queued": "已接纳，等待执行",
    "running": "执行中",
    "completed": "审核通过",
    "needs_input": "需要补充输入",
    "review_failed": "审核未通过",
    "failed": "执行失败",
    "passed": "已完成",
}
CASE_NAMES = {"错误事实": "bad-fact", "缺失章节": "missing-section", "持续错误": "always-bad"}


def _controller() -> RunController:
    if "office_run_controller" not in st.session_state:
        st.session_state.office_run_controller = RunController()
    return st.session_state.office_run_controller


def _input_panel(controller: RunController) -> None:
    snapshot = controller.snapshot()
    retained = snapshot is not None
    with st.sidebar:
        st.markdown("### 创建报告任务")
        st.caption("提交时冻结输入；修改页面、轮询或下载不会重新调用模型。")
        if retained:
            st.info("本会话已保留一个任务。结束后点击“新建任务”再提交。")
        with st.form("office_task_form"):
            request = st.text_area("报告需求", value=DEFAULT_REQUEST, height=170, disabled=retained)
            origin = st.radio("数据来源", ["实验样例", "上传我的文件"], disabled=retained)
            uploads = st.file_uploader(
                "上传 projects.csv、achievements.csv、issues.txt",
                type=["csv", "txt"],
                accept_multiple_files=True,
                max_upload_size=2,
                disabled=retained,
                help="必须齐备三个固定文件。UTF-8编码，每个文件最多2 MiB。",
            )
            st.caption("选择实验样例时，已上传的文件不会参与本次运行。")
            mode_label = st.radio("模型模式", ["离线模拟", "真实模型"], disabled=retained)
            st.caption("离线模式不读取密钥、不产生模型费用；真实模式使用服务器本地配置。")
            with st.expander("运行预算"):
                revisions = st.number_input("最多返工次数", 0, 2, 2, disabled=retained)
                retries = st.number_input("网络重试预算", 0, 2, 0, disabled=retained)
                requests = st.number_input("HTTP请求上限", 1, 12, 10, disabled=retained)
                tokens = st.number_input("输出tokens预留上限", 1, 5568, 4032, disabled=retained)
                timeout = st.number_input("单次请求超时（秒）", 1, 300, 30, disabled=retained)
                st.caption("预算为硬上限；预留输出量与模型实际消耗不同。")
            with st.expander("故障实验（主动注入）"):
                experiment = st.checkbox("启用故意注入错误的实验", disabled=retained)
                case_label = st.selectbox("注入场景", list(CASE_NAMES), disabled=retained)
                st.caption("仅用于演示审核和返工；主动注入不能当作模型自然错误。")
            submitted = st.form_submit_button(
                "开始协作", type="primary", width="stretch", disabled=retained
            )
        if submitted:
            try:
                prepared = prepare_input(
                    ()
                    if origin == "实验样例"
                    else tuple(UploadBlob(item.name, item.getvalue()) for item in uploads),
                    use_samples=origin == "实验样例",
                )
                options = WebRunOptions(
                    request=request,
                    mode="live" if mode_label == "真实模型" else "mock",
                    max_revisions=int(revisions),
                    retry_budget=int(retries),
                    max_requests=int(requests),
                    max_output_tokens=int(tokens),
                    timeout_seconds=float(timeout),
                    test_scenario=CASE_NAMES[case_label] if experiment else "none",
                )
                admitted = controller.start(options=options, prepared=prepared)
                if admitted:
                    st.session_state.pop("office_input_error", None)
                    st.session_state.pop("office_input_issues", None)
                    st.rerun()
                else:
                    st.session_state.office_input_error = "任务已接纳，请等待当前任务结束。"
            except WebInputError as error:
                st.session_state.office_input_error = str(error)
                st.session_state.office_input_issues = [
                    issue.model_dump(mode="json") for issue in error.issues
                ]
            except (ValidationError, ValueError):
                st.session_state.pop("office_input_issues", None)
                st.session_state.office_input_error = "输入或预算无效，请检查需求与配置。"
            except Exception:
                st.session_state.pop("office_input_issues", None)
                st.session_state.office_input_error = "任务未能启动，请检查本地配置后重试。"
        if "office_input_error" in st.session_state:
            st.error(st.session_state.office_input_error)
            if st.session_state.get("office_input_issues"):
                st.dataframe(st.session_state.office_input_issues, hide_index=True)
        st.divider()
        st.caption("本机实验原型 · v0.6\n\n每个浏览器会话独立；重启服务不恢复后台任务。")


def _role_progress(snapshot: JobSnapshot) -> None:
    st.subheader("协作进度")
    columns = st.columns(len(ROLES))
    for column, (role, label) in zip(columns, ROLES.items(), strict=True):
        events = [
            event
            for event in snapshot.events
            if event.role == role and event.event_type in {"node_started", "node_finished"}
        ]
        with column:
            st.markdown(f"**{label}**")
            if events:
                event = events[-1]
                st.caption(f"第 {event.revision_index} 轮 · {STATUSES[event.status]}")
            else:
                st.caption("尚未开始")
    st.caption("第0轮为初稿，后续轮次为返工。状态来自真实工作流事件。")
    if snapshot.events:
        with st.expander("运行日志与工具记录"):
            st.dataframe(
                [
                    {
                        "角色": ROLES[event.role],
                        "轮次": event.revision_index,
                        "事件": event.event_type,
                        "状态": STATUSES[event.status],
                        "工具": event.tool_name or "—",
                        "耗时ms": event.duration_ms,
                        "说明": event.summary,
                    }
                    for event in snapshot.events
                ],
                hide_index=True,
                width="stretch",
            )


def _results(snapshot: JobSnapshot) -> None:
    result = snapshot.result
    if result is None:
        return
    st.subheader("结果与依据")
    st.caption(
        f"模式：{'真实模型' if result.mode == 'live' else '离线模拟模型'} · "
        f"数据：{'实验模拟数据' if result.data_origin == 'simulated' else '用户提供数据'}"
    )
    if result.test_scenario != "none":
        st.warning(f"故障实验：{result.test_scenario}。本次错误为主动注入，不能当作自然模型错误。")
    usage = result.usage.get("total_tokens")
    st.write(
        f"HTTP请求 {result.request_count} 次 · 输出预留 {result.reserved_output_tokens} tokens · "
        f"实际总tokens {'不可用' if usage is None else usage} · "
        f"返工启动 {result.revision_count}/{result.max_revisions} · "
        f"网络重试 {result.retry_count}/{result.retry_budget}"
    )
    if result.metrics:
        names = {
            "project_count": "项目数",
            "completed_project_count": "已完成项目数",
            "completion_rate": "项目完成率",
            "achievement_count": "成果数",
        }
        columns = st.columns(4)
        for column, metric in zip(columns, result.metrics, strict=False):
            value = metric.value
            if metric.metric_id == "completion_rate" and value is not None:
                value = f"{value:.1%}"
            column.metric(names[metric.metric_id], "不可用" if value is None else value)
        st.caption("项目完成率仅是输入数据的业务统计，不代表项目开发完成率。")
    if result.requirements:
        with st.expander("已确认需求与报告大纲"):
            st.json(result.requirements.model_dump(mode="json"))
            if result.outline:
                st.json(result.outline.model_dump(mode="json"))
    elif result.manager_decision:
        with st.expander("需求补充提示", expanded=True):
            st.json(result.manager_decision.model_dump(mode="json"))
    if result.sources:
        with st.expander("统计来源与行号"):
            st.dataframe(
                [source.model_dump(mode="json") for source in result.sources],
                hide_index=True,
                width="stretch",
            )
            st.json([metric.model_dump(mode="json") for metric in result.metrics])
    if result.data_issues:
        with st.expander("数据检查结果", expanded=True):
            st.json([issue.model_dump(mode="json") for issue in result.data_issues])
    for revision in result.revision_history:
        review = revision.review
        with st.expander(
            f"第 {revision.revision_index} 轮草稿 · {'审核通过' if review.passed else '审核未通过'}"
        ):
            st.caption(
                "程序与模型共同审核"
                if revision.review_mode == "program_and_model"
                else "程序发现错误，本轮未调用审核模型"
            )
            st.json(review.model_dump(mode="json"))
            st.markdown(revision.draft.markdown)
    reviewed = {revision.revision_index for revision in result.revision_history}
    for node in result.nodes:
        if (
            node.role == "writer"
            and node.output is not None
            and node.revision_index not in reviewed
        ):
            with st.expander(f"第 {node.revision_index} 轮草稿 · 待审核"):
                st.caption("Checker尚未完成，当前草稿不是最终报告。")
                st.markdown(node.output.get("markdown", ""))
    final = next((item for item in snapshot.downloads if item.name == "report.md"), None)
    if snapshot.status == "completed" and result.status == "completed" and final is not None:
        st.subheader("最终工作报告")
        st.caption("已通过最终导出门禁。建议尚未实施，需人工评估。")
        st.markdown(final.data.decode("utf-8"))
    else:
        st.info("当前没有通过最终门禁的报告；可查看草稿、审核意见与运行记录。")
    if snapshot.downloads:
        st.subheader("下载本次产物")
        for artifact in snapshot.downloads:
            if artifact.name == "report.md" and (
                snapshot.status != "completed" or result.status != "completed"
            ):
                continue
            st.download_button(
                "下载最终报告" if artifact.name == "report.md" else f"下载 {artifact.name}",
                data=artifact.data,
                file_name=f"{snapshot.run_id}-{artifact.name.replace('/', '-')}",
                mime=artifact.mime,
                on_click="ignore",
                key=f"download-{snapshot.run_id}-{artifact.name}",
            )


@st.fragment(run_every=0.5)
def _status_panel() -> None:
    snapshot = _controller().snapshot()
    if snapshot is None:
        st.info("在左侧填写需求并开始协作。默认样例可直接离线运行。")
        return
    st.markdown(f"### {STATUSES[snapshot.status]}")
    st.caption(f"运行编号：{snapshot.run_id}")
    _role_progress(snapshot)
    if snapshot.error:
        st.error(snapshot.error)
    _results(snapshot)
    # This button lives inside the polling fragment, so completion enables it
    # without requiring a manual full-page refresh. Reset explicitly reruns the app.
    if st.button("新建任务", disabled=snapshot.status in {"queued", "running"}):
        if _controller().reset():
            st.session_state.pop("office_input_error", None)
            st.session_state.pop("office_input_issues", None)
            st.rerun()


def render_app() -> None:
    st.set_page_config(page_title="多智能体办公工作台", page_icon="🗂️", layout="wide")
    st.markdown(
        "<style>.block-container{padding-top:2rem;}"
        "[data-testid='stSidebar']{background:#f4f7fb;}"
        "h1{letter-spacing:-.02em;}"
        "[data-testid='stMetric']{background:#f4f7fb;padding:1rem;border-radius:.6rem;}"
        "</style>",
        unsafe_allow_html=True,
    )
    st.title("多智能体办公工作台")
    st.markdown("从需求到报告，让五位助手协作完成规划、统计、撰写与审核。")
    st.caption("LangGraph 工作流 · 可追溯数据来源 · 有界返工与请求预算")
    controller = _controller()
    _input_panel(controller)
    _status_panel()
