"""Company-sized synthetic files have stable keys, real tool validation and no paid calls."""

import csv
import hashlib
import io
import json
import runpy
from pathlib import Path

import pytest
from test_workbench_execution_acceptance import finished, submit, workbench

ROOT = Path(__file__).resolve().parents[1] / "data/enterprise-office"
MANIFEST = json.loads((ROOT / "manifest.json").read_text())


def test_enterprise_files_are_reproducible_and_have_unique_related_records(tmp_path):
    generate = runpy.run_path(str(ROOT / "generate.py"))["generate"]
    assert generate(tmp_path) == MANIFEST
    keys = {kind: set() for kind in ("projects", "attendance", "achievements", "satisfaction")}
    project_ids, associated = set(), set()
    for item in MANIFEST["files"]:
        raw = (ROOT / item["path"]).read_bytes()
        assert (tmp_path / item["path"]).read_bytes() == raw
        assert hashlib.sha256(raw).hexdigest() == item["sha256"]
        if item["kind"] == "notes":
            continue
        rows = list(csv.DictReader(io.StringIO(raw.decode())))
        assert len(rows) == item["rows"]
        fields = {
            "projects": ("project_id", "snapshot_date"),
            "attendance": ("person_id", "date"),
            "achievements": ("achievement_id",),
            "satisfaction": ("feedback_id",),
        }[item["kind"]]
        for row in rows:
            key = tuple(row[field] for field in fields)
            assert key not in keys[item["kind"]]
            keys[item["kind"]].add(key)
            day = row["snapshot_date"] if item["kind"] == "projects" else row["date"]
            assert item["start_date"] <= day < item["end_date"]
            assert day <= MANIFEST["as_of"]
            if item["kind"] == "projects":
                project_ids.add(row["project_id"])
            elif row.get("project_id"):
                associated.add(row["project_id"])
    assert len(project_ids) == 80 and associated <= project_ids
    assert MANIFEST["total_rows"] == 20520


@pytest.mark.parametrize(
    "case", MANIFEST["expected"], ids=lambda case: case["department"] + case["period"]
)
def test_each_company_department_period_runs_the_real_five_roles_offline(tmp_path, case):
    import_files = runpy.run_path(str(ROOT / "import_materials.py"))["import_files"]
    # Import one department/period through the real API, using its published manifest.
    subset = [
        item
        for item in MANIFEST["files"]
        if item["department"] == case["department"] and case["period"] in item["path"]
    ]
    (tmp_path / "manifest.json").write_text(json.dumps(dict(files=subset)))
    for item in subset:
        target = tmp_path / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / item["path"]).read_bytes())
    with workbench(tmp_path) as (client, _):
        assert import_files(client, tmp_path) == dict(imported=5, skipped=0)
        assert import_files(client, tmp_path) == dict(imported=0, skipped=5)
        materials = client.get("/api/v1/materials").json()["items"]
        start, end = subset[0]["start_date"], subset[0]["end_date"]
        response = submit(
            client,
            materials,
            text=(
                f"生成{case['department']}{start}至{end}（不含结束日）的工作汇报，"
                "包含项目进度、人员考勤、成果和服务满意度，标明样本及期间限制。"
            ),
        )
        assert response.status_code == 202, response.text
        final = finished(client, response.json()["id"], timeout=45, poll_interval=0.1)
        assert final["status"] == "completed", final.get("error")
        assert [node["role"] for node in final["nodes"]] == [
            "manager",
            "planner",
            "data",
            "writer",
            "checker",
            "manager",
        ]
        assert final["usage"]["request_count"] == 0
        facts = {fact["metric_id"]: fact["value"] for fact in final["facts"]}
        assert facts["project_count"] == case["project_count"]
        assert facts["completed_project_count"] == case["project_states"]["completed"]
        assert facts["person_days"] == case["attendance_rows"]
        assert facts["achievement_count"] == case["achievements"]
        assert facts["satisfaction_count_0"] == case["valid_feedback"]
