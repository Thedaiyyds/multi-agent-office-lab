"""Agent-selected windows use real record dates; numeric references remain validated."""

from copy import deepcopy

import httpx
import pytest
from test_workbench_execution_acceptance import ScriptedProvider, submit, upload, workbench
from test_workbench_planning import approve, confirmation

from office_agents.workbench.execution import render_markdown, validate_narrative


def example(client):
    return upload(
        client,
        "近期成果.csv",
        "achievements",
        "achievement_id,department,date,category,name,project_id\n"
        "A1,技术部,2026-10-08,交付,接口上线,P1\n"
        "A2,技术部,2026-10-21,交付,报表上线,P2\n".encode(),
        department="技术部",
        start="2026-10-01",
        end="2027-01-01",
    )


def plan(client, app, text="根据材料规划汇报", mode="offline_mock"):
    response = submit(client, [example(client)], text=text, planning_only=True, mode=mode)
    assert app.state.execution_service.wait_for_idle(10)
    return client.get("/api/v1/runs/" + response.json()["id"]).json()


def test_blank_request_uses_actual_days_and_whole_period_without_quarter_padding(tmp_path):
    with workbench(tmp_path) as (client, app):
        run = plan(client, app)
        assert run["status"] == "awaiting_confirmation", run.get("error")
        assert run["requirements"]["start_date"] == "2026-10-08"
        assert run["requirements"]["end_date"] == "2026-10-22"
        assert not run["outline"].get("periods")
        assert approve(client, run).status_code == 202
        assert app.state.execution_service.wait_for_idle(10)
        final = client.get("/api/v1/runs/" + run["id"]).json()
        assert final["status"] == "completed", final.get("error")
        assert "2026-10-08 至 2026-10-21" in final["draft_markdown"]
        assert "2027-01-01" not in final["draft_markdown"]
        assert [node["role"] for node in final["nodes"]] == [
            "manager",
            "planner",
            "data",
            "writer",
            "checker",
            "manager",
        ]
        assert (
            next(f["value"] for f in final["facts"] if f["metric_id"] == "achievement_count") == 2
        )
        # New value references expand numbers only, but cannot authorize unknown facts.
        changed = deepcopy(final)
        changed["narrative"]["sections"][0]["text"] = "已完成成果[[value:F001]]，详见统计附录。"
        changed["draft_markdown"] = render_markdown(changed, changed["narrative"])
        assert not validate_narrative(changed)
        assert "[[value:" not in changed["draft_markdown"]
        assert "（F001）" not in changed["draft_markdown"].split("## 权威统计与口径")[0]
        changed["narrative"]["sections"][0]["text"] = "[[value:F999]]"
        changed["draft_markdown"] = render_markdown(changed, changed["narrative"])
        assert "引用了未授权的事实或文字片段" in validate_narrative(changed)


def test_model_can_select_a_week_different_from_inventory_envelope(tmp_path):
    def adapt(role, phase, context, reply):
        if phase == "requirements":
            reply["requirements"].update(
                context["suggested_scope"],
                start_date="2026-10-15",
                end_date="2026-10-22",
                title="近期交付情况",
            )
        if phase == "outline":
            reply["groups"] = ["achievements"]
            for section in reply["sections"]:
                section["groups"] = ["achievements"]
        return reply

    with workbench(tmp_path, transport=httpx.MockTransport(ScriptedProvider(adapt))) as (
        client,
        app,
    ):
        run = plan(client, app, mode="live")
        assert run["status"] == "awaiting_confirmation", run.get("error")
        assert run["requirements"]["start_date"] == "2026-10-15"
        assert approve(client, run).status_code == 202
        assert app.state.execution_service.wait_for_idle(10)
        final = client.get("/api/v1/runs/" + run["id"]).json()
        assert final["status"] == "completed", final.get("error")
        assert (
            next(f["value"] for f in final["facts"] if f["metric_id"] == "achievement_count") == 1
        )


@pytest.mark.parametrize(
    "periods",
    [
        [{"start_date": "2026-10-01", "end_date": "2026-10-22"}],
        [
            {"start_date": "2026-10-08", "end_date": "2026-10-18"},
            {"start_date": "2026-10-15", "end_date": "2026-10-22"},
        ],
    ],
)
def test_confirm_rejects_outside_or_overlapping_segments_before_creating_report(tmp_path, periods):
    with workbench(tmp_path) as (client, app):
        run = plan(client, app)
        body = confirmation(run)
        body["outline"]["periods"] = periods
        assert approve(client, run, body).status_code == 422
        assert client.get("/api/v1/reports").json()["items"] == []


def test_explicit_quarter_preserves_requested_window_and_discloses_actual_cutoff(tmp_path):
    with workbench(tmp_path) as (client, app):
        run = plan(client, app, "规划技术部2026年第四季度汇报")
        assert run["status"] == "awaiting_confirmation", run.get("error")
        assert run["requirements"]["end_date"] == "2027-01-01"
        assert approve(client, run).status_code == 202
        assert app.state.execution_service.wait_for_idle(10)
        final = client.get("/api/v1/runs/" + run["id"]).json()
        assert final["status"] == "completed", final.get("error")
        assert final["statistics"]["coverage_scopes"][0]["end_date"] == "2026-10-22"
        assert "2026-10-01 至 2026-12-31" in final["draft_markdown"]
        assert "2026-10-08 至 2026-10-21" in final["draft_markdown"]


def test_planner_model_can_choose_custom_segments_without_a_quarter_prompt(tmp_path):
    def adapt(role, phase, context, reply):
        if phase == "requirements":
            reply["requirements"].update(context["suggested_scope"])
        if phase == "outline":
            reply["groups"] = ["achievements"]
            reply["periods"] = [
                dict(start_date="2026-10-08", end_date="2026-10-15"),
                dict(start_date="2026-10-15", end_date="2026-10-22"),
            ]
            for section in reply["sections"]:
                section["groups"] = ["achievements"]
        if phase == "draft":
            for section in reply["sections"]:
                section["text"] = "技术部交付成果可按阶段查看，具体数值见附录。"
        return reply

    with workbench(tmp_path, transport=httpx.MockTransport(ScriptedProvider(adapt))) as (
        client,
        app,
    ):
        run = plan(client, app, mode="live")
        assert run["status"] == "awaiting_confirmation", run.get("error")
        assert len(run["outline"]["periods"]) == 2
        assert approve(client, run).status_code == 202
        assert app.state.execution_service.wait_for_idle(10)
        final = client.get("/api/v1/runs/" + run["id"]).json()
        assert final["status"] == "completed", final.get("error")
        counts = [
            fact["value"]
            for fact in final["facts"]
            if fact["metric_id"].endswith("achievement_count")
        ]
        assert counts == [1, 1]
        assert len(final["statistics"]["data_scopes"]) == 2


def test_business_display_does_not_change_legacy_render_or_numeric_evidence():
    from office_agents.workbench.execution import display_fact_value

    fact = dict(
        id="F001",
        label="满意度",
        value=3.970588235,
        unit="分",
        definition="样本均分",
        limitations=[],
        source_refs=[],
    )
    run = dict(
        requirements=dict(
            title="工作汇报", department="技术部", start_date="2026-10-08", end_date="2026-10-22"
        ),
        facts=[fact],
        notes=[],
        statistics={},
        mode="live",
    )
    narrative = dict(sections=[dict(title="概况", text="[[fact:F001]]")], suggestions=[])
    legacy = render_markdown(run, narrative)
    assert "满意度：3.97059分（F001）" in legacy
    assert "2026-10-22（不含）" in legacy
    run["statistics"]["presentation"] = "business-v1"
    current = render_markdown(run, narrative)
    assert "满意度：3.97分" in current
    assert "2026-10-08 至 2026-10-21" in current
    assert fact["value"] == 3.970588235
    run["statistics"].clear()
    assert render_markdown(run, narrative) == legacy
    assert display_fact_value(dict(value=None, unit="个")) == "材料不足，暂不计算"
