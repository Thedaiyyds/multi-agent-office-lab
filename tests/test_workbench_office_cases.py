"""Larger ordinary cases exercise the actual graph and exports without paid calls."""

import json
import time
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfReader
from test_workbench_execution_acceptance import (
    finished,
    ordinary_case,
    submit,
    upload,
    workbench,
)

from office_agents.workbench.execution import _grouped_source_lines, render_markdown

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("department", ["技术部", "行政部"])
def test_large_fixed_interface_graph_and_both_exports(tmp_path, department):
    examples = [
        line.removeprefix("> ")
        for line in (ROOT / "data/office-cases/README.md").read_text().splitlines()
        if line.startswith("> 请生成")
    ]
    text = examples[0 if department == "技术部" else 1]
    with workbench(tmp_path) as (client, _):
        response = submit(client, [], text, use_local_api=True)
        assert response.status_code == 202, response.text
        run = finished(client, response.json()["id"])
        assert run["status"] == "completed", run.get("error")
        assert [node["role"] for node in run["nodes"]] == [
            "manager",
            "planner",
            "data",
            "writer",
            "checker",
            "manager",
        ]
        assert run["usage"]["request_count"] == 0
        assert run["usage"]["mock_calls"] == 6
        assert run["statistics"]["source_format"] == "grouped-v1"
        assert run["notes"], "The fixed interface must also freeze the case background text"
        assert len({note["material_id"] for note in run["notes"]}) == 1
        writer = next(node for node in run["nodes"] if node["role"] == "writer")
        assert writer["inputs"]["context"]["notes"] == run["notes"]
        assert len(run["draft_markdown"]) < 80_000
        values = {fact["metric_id"]: fact["value"] for fact in run["facts"]}
        if department == "技术部":
            assert values["project_count"] == 12
            assert values["achievement_count"] == 42
            assert values["person_days"] == 1560
            assert values["attendance_rate"] is None
            assert values["attendance_coverage"] is None
            person_days = next(f for f in run["facts"] if f["metric_id"] == "person_days")
            assert len(person_days["source_refs"]) == 1560
            legacy = json.loads(json.dumps(run))
            legacy["statistics"].pop("source_format")
            legacy_md = render_markdown(legacy, legacy["narrative"])
            assert len(legacy_md) > len(run["draft_markdown"]) * 10
            assert f"- {person_days['id']}：" in legacy_md
        base = f"/api/v1/reports/{run['report_id']}/revisions"
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            revisions = client.get(base).json()["items"]
            if revisions and all(a["state"] == "ready" for a in revisions[0]["artifacts"]):
                break
            time.sleep(0.05)
        assert revisions
        revision = revisions[0]
        assert revision["status"] == "approved"
        files = base + "/" + revision["id"] + "/exports/"
        md, pdf = client.get(files + "md"), client.get(files + "pdf")
        assert md.status_code == pdf.status_code == 200
        assert md.content == run["draft_markdown"].encode()
        pages = PdfReader(BytesIO(pdf.content)).pages
        assert 1 <= len(pages) <= 15
        extracted = "\n".join(page.extract_text() for page in pages)
        assert department in extracted and "数据限制与来源" in extracted
        assert run["source_datasets"][0]["sha256"] in "".join(extracted.split())


def test_grouped_sources_preserve_gaps_fields_hashes_and_non_csv_locations():
    def ref(location, **changes):
        return dict(
            material_id="m1",
            name="材料.csv",
            version=1,
            sha256="abc",
            fields=["actual_hours"],
            location=location,
            **changes,
        )

    refs = [ref("行 2"), ref("行 3"), ref("行 5"), ref("表格 1 / 行 4")]
    refs.append({**ref("行 2"), "fields": ["planned_hours"]})
    refs.append({**ref("行 7"), "sha256": "different"})
    lines = _grouped_source_lines([dict(id="F001", source_refs=refs)])
    assert len(lines) == 3
    assert "行 2–3、行 5、表格 1 / 行 4" in lines[0]
    assert "行 2–5" not in lines[0]
    assert "SHA256 abc" in lines[0] and "actual_hours" in lines[0]
    assert "planned_hours" in lines[1] and "different" in lines[2]


def test_text_selection_limits_are_visible_to_roles_and_export(tmp_path):
    with workbench(tmp_path) as (client, _):
        materials = ordinary_case(client)
        note = upload(
            client,
            "长工作记录.txt",
            "notes",
            ("甲" * 1200 + "\n" + ("乙" * 900 + "\n") * 8).encode(),
            department="技术部",
            start="2026-04-01",
            end="2026-07-01",
        )
        response = submit(client, materials + [note])
        run = finished(client, response.json()["id"])
        assert run["status"] == "completed"
        limitation = run["statistics"]["note_limitations"][0]
        assert "截短" in limitation and "未纳入" in limitation
        writer = next(node for node in run["nodes"] if node["role"] == "writer")
        assert writer["inputs"]["context"]["data_limitations"] == [limitation]
        checker = next(node for node in run["nodes"] if node["role"] == "checker")
        assert checker["inputs"]["context"]["data_limitations"] == [limitation]
        assert limitation in run["nodes"][-1]["inputs"]["context"]["limitations"]
        assert limitation in run["draft_markdown"]
        assert any(limitation in event["message"] for event in run["events"])
