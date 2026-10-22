"""Exercise large planning at the HTTP/model boundary, where offline mocks skip size guards."""

import json
import runpy
import time
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from test_workbench_execution_acceptance import ScriptedProvider, submit, upload, workbench
from test_workbench_planning import approve

from office_agents.workbench.execution import compact_model_context
from office_agents.workbench.materials import canonical_json

ROOT = Path(__file__).resolve().parents[1]


def test_large_context_shares_metadata_losslessly_without_changing_original():
    context = dict(
        facts=[
            dict(id=f"F{i:03}", label="指标", value=i, unit="条", limitations=["限制" * 50])
            for i in range(1, 160)
        ],
        notes=[
            dict(
                id=f"N{i:03}",
                text="保持原文" * 20,
                location=f"行 {i}",
                material_id="m1",
                name="材料.txt",
                version=1,
                sha256="a" * 64,
                scope=dict(department="技术部", start_date="2026-07-01", end_date="2026-10-01"),
            )
            for i in range(1, 100)
        ],
    )
    original = deepcopy(context)
    compact = compact_model_context(context)
    assert context == original
    assert compact_model_context(compact) == compact
    assert len(canonical_json(compact)) < len(canonical_json(context)) * 0.65
    for fact, expected in zip(compact["facts"], original["facts"], strict=True):
        restored = dict(fact)
        restored["limitations"] = [
            compact["fact_limitations"][key] for key in restored.pop("limitation_ids")
        ]
        assert restored == expected
    for note, expected in zip(compact["notes"], original["notes"], strict=True):
        restored = dict(note)
        restored.update(compact["note_sources"][restored.pop("source_id")])
        assert restored == expected


@pytest.mark.parametrize("mode", ["live", "offline_mock"])
def test_all_library_files_no_hint_default_confirmation_completes_through_model_transport(
    tmp_path, mode
):
    sizes = []

    def adapt(role, phase, context, reply):
        if phase == "requirements":
            reply["requirements"].update(context["suggested_scope"])
            reply["requirements"]["title"] = context["suggested_title"]
        if phase == "outline":
            reply["groups"] = context["available_groups"]
            for section in reply["sections"]:
                section["groups"] = context["available_groups"]
        if phase == "draft":
            for index, section in enumerate(reply["sections"]):
                sample = context["facts"][index :: len(reply["sections"])][:3]
                section["text"] = "依据授权样本整理，完整数值见附表。" + " ".join(
                    f"[[fact:{fact['id']}]]" for fact in sample
                )
        return reply

    provider = ScriptedProvider(adapt)

    def transport(request):
        body = json.loads(request.content)
        sizes.append(len(canonical_json(body["messages"])))
        assert sizes[-1] <= 64000
        return provider(request)

    with workbench(tmp_path, transport=httpx.MockTransport(transport)) as (client, app):
        importer = runpy.run_path(str(ROOT / "data/enterprise-office/import_materials.py"))[
            "import_files"
        ]
        assert importer(client, ROOT / "data/enterprise-office")["imported"] == 40
        for folder, department, start, end, files in [
            (
                "technical-q2",
                "技术部",
                "2026-04-01",
                "2026-07-01",
                [
                    ("项目进度.csv", "projects"),
                    ("人员考勤.csv", "attendance"),
                    ("成果统计.csv", "achievements"),
                    ("工作说明.txt", "notes"),
                ],
            ),
            (
                "administration-q1",
                "行政部",
                "2026-01-01",
                "2026-04-01",
                [("满意度.csv", "satisfaction"), ("服务说明.txt", "notes")],
            ),
        ]:
            for name, kind in files:
                upload(
                    client,
                    name,
                    kind,
                    (ROOT / "data/office-cases" / folder / name).read_bytes(),
                    department=department,
                    start=start,
                    end=end,
                )
        for folder, name, department, start, end in [
            ("technical-q2", "季度工作记录.docx", "技术部", "2026-04-01", "2026-07-01"),
            ("administration-q1", "服务记录.docx", "行政部", "2026-01-01", "2026-04-01"),
        ]:
            upload(
                client,
                name,
                "notes",
                (ROOT / "data/demo" / folder / name).read_bytes(),
                department=department,
                start=start,
                end=end,
            )
        materials = client.get("/api/v1/materials").json()["items"]
        assert len(materials) == 48
        response = submit(
            client,
            materials,
            text="根据所选材料提出一份工作汇报方案",
            mode=mode,
            planning_only=True,
        )
        assert response.status_code == 202
        assert app.state.execution_service.wait_for_idle(90)
        run_id = response.json()["id"]
        plan = client.get("/api/v1/runs/" + run_id).json()
        assert plan["status"] == "awaiting_confirmation", plan.get("error")
        assert approve(client, plan).status_code == 202
        assert app.state.execution_service.wait_for_idle(90)
        result = client.get("/api/v1/runs/" + run_id).json()
        assert result["status"] == "completed", result.get("error")
        assert len(sizes) == (6 if mode == "live" else 0)
        assert len(result["nodes"]) == 6
        assert len(result["facts"]) > 140 and len(result["notes"]) > 50
        assert len(result["data_scopes"]) == 10
        for role in ("data", "writer", "checker"):
            context = next(node for node in result["nodes"] if node["role"] == role)["inputs"][
                "context"
            ]
            assert context["note_sources"] and context["fact_limitations"]
            assert {fact["id"] for fact in context["facts"]} == {
                fact["id"] for fact in result["facts"]
            }
            assert {note["id"] for note in context["notes"]} == {
                note["id"] for note in result["notes"]
            }
        base = f"/api/v1/reports/{result['report_id']}/revisions"
        deadline = time.monotonic() + 30
        revisions = []
        while time.monotonic() < deadline:
            revisions = client.get(base).json()["items"]
            if revisions and all(item["state"] == "ready" for item in revisions[0]["artifacts"]):
                break
            time.sleep(0.1)
        assert revisions
        for fmt in ("md", "pdf"):
            response = client.get(f"{base}/{revisions[0]['id']}/exports/{fmt}")
            assert response.status_code == 200 and response.content
