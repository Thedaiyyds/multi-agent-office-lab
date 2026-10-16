"""Synthetic demo cases must stay reproducible, explicit, and isolated.

No credentials or provider calls are used. All persistent writes target tmp_path.
"""

import csv
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from office_agents.workbench import create_app

DEMO = {"X-Workspace": "demo"}
FIXTURES = Path(__file__).resolve().parents[1] / "data" / "demo"


@pytest.fixture
def demo_client(tmp_path):
    with TestClient(create_app(tmp_path / "demo.sqlite3", static_dir=False)) as client:
        yield client


def test_demo_endpoints_are_explicit_and_forbidden_in_normal_space(demo_client):
    assert demo_client.get("/api/v1/materials").json() == {"items": []}
    for method, path, payload in [
        ("GET", "/api/v1/demo/catalog", None),
        ("GET", "/api/v1/demo/provider/projects", None),
        ("POST", "/api/v1/demo/load", None),
        ("POST", "/api/v1/materials/from-demo-api", {"kind": "projects"}),
    ]:
        response = demo_client.request(method, path, json=payload)
        assert response.status_code == 403
    assert demo_client.get("/api/v1/materials").json() == {"items": []}


def test_demo_catalog_matches_actual_synthetic_files(demo_client):
    response = demo_client.get("/api/v1/demo/catalog", headers=DEMO)
    assert response.status_code == 200
    catalog = response.json()
    assert catalog["case"] == "technical-q2"
    assert "2026" in catalog["request"]
    assert {item["name"] for item in catalog["files"]} == {
        "项目进度.csv",
        "人员考勤.csv",
        "成果统计.csv",
        "工作说明.txt",
        "季度工作记录.docx",
    }
    for item in catalog["files"]:
        assert (FIXTURES / "technical-q2" / item["name"]).is_file()
    assert demo_client.get("/api/v1/materials", headers=DEMO).json() == {"items": []}


def test_explicit_demo_load_is_deduplicated_scoped_and_persistent(tmp_path):
    database = tmp_path / "demo.sqlite3"
    with TestClient(create_app(database, static_dir=False)) as client:
        first = client.post("/api/v1/demo/load", headers=DEMO)
        assert first.status_code == 200
        loaded = first.json()
        assert loaded["case"] == "technical-q2"
        assert loaded["already_loaded"] is False
        materials = loaded["materials"]
        assert len(materials) == 5
        ids = {item["id"] for item in materials}
        assert len(ids) == 5
        assert {item["kind"] for item in materials} == {
            "projects",
            "attendance",
            "achievements",
            "notes",
        }
        assert all(item["workspace"] == "demo" for item in materials)
        assert all(item["version"] == 1 for item in materials)
        by_name = {item["name"]: item for item in materials}
        assert by_name["项目进度.csv"]["mapping"]["completed_date"] == "completed_date"
        assert by_name["人员考勤.csv"]["mapping"]["leave_hours"] == "leave_hours"
        assert by_name["成果统计.csv"]["mapping"]["project_id"] == "project_id"
        word_preview = by_name["季度工作记录.docx"]["preview"]
        assert any(row["location"].startswith("段落") for row in word_preview)
        assert any(row["location"].startswith("表格") for row in word_preview)
        repeated = client.post("/api/v1/demo/load", headers=DEMO).json()
        assert repeated["already_loaded"] is True
        assert {item["id"] for item in repeated["materials"]} == ids
        assert len(client.get("/api/v1/materials", headers=DEMO).json()["items"]) == 5
        assert client.get("/api/v1/materials").json() == {"items": []}
        assert client.get("/api/v1/reports").json() == {"items": []}
        for material in materials:
            detail_url = f"/api/v1/materials/{material['id']}"
            assert client.get(detail_url).status_code == 404
            assert client.get(detail_url + "/download").status_code == 404
            original = client.get(detail_url + "/download", headers=DEMO)
            assert original.status_code == 200
            assert original.content == (FIXTURES / "technical-q2" / material["name"]).read_bytes()
    with TestClient(create_app(database, static_dir=False)) as restarted:
        assert {
            item["id"] for item in restarted.get("/api/v1/materials", headers=DEMO).json()["items"]
        } == ids


@pytest.mark.parametrize("kind", ["projects", "attendance", "achievements", "satisfaction"])
def test_local_demo_provider_can_freeze_and_confirm_without_external_requests(demo_client, kind):
    provider = demo_client.get(f"/api/v1/demo/provider/{kind}", headers=DEMO)
    assert provider.status_code == 200
    data = provider.json()
    assert data["source"] == "local_demo_api"
    assert data["records"]
    imported = demo_client.post(
        "/api/v1/materials/from-demo-api", headers=DEMO, json={"kind": kind}
    )
    assert imported.status_code == 201
    staged = imported.json()
    assert staged["source"] == "local_api"
    assert staged["kind"] == kind
    assert staged["row_count"] == len(data["records"])
    assert demo_client.get("/api/v1/materials", headers=DEMO).json() == {"items": []}
    confirmed = demo_client.post(
        f"/api/v1/imports/{staged['id']}/confirm",
        headers=DEMO,
        json={"mapping": staged["suggested_mapping"]},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["row_count"] == len(data["records"])
    assert demo_client.get("/api/v1/materials").json() == {"items": []}


def test_demo_does_not_accept_arbitrary_remote_sources_or_invalid_kind(demo_client):
    response = demo_client.post(
        "/api/v1/materials/from-demo-api",
        headers=DEMO,
        json={"kind": "projects", "url": "https://example.invalid/private"},
    )
    assert response.status_code == 422
    assert demo_client.get("/api/v1/demo/provider/unknown", headers=DEMO).status_code == 422
    assert (
        demo_client.post(
            "/api/v1/materials/from-demo-api", headers=DEMO, json={"kind": "notes"}
        ).status_code
        == 422
    )
    assert demo_client.get("/api/v1/materials", headers=DEMO).json() == {"items": []}


def test_independent_demo_database_never_seeds_normal_database(tmp_path):
    normal_database = tmp_path / "normal" / "workbench.sqlite3"
    demo_database = tmp_path / "demo" / "workbench.sqlite3"
    with TestClient(create_app(normal_database, static_dir=False)) as normal:
        with TestClient(create_app(demo_database, static_dir=False)) as demo:
            assert demo.post("/api/v1/demo/load", headers=DEMO).status_code == 200
            for headers in ({}, DEMO):
                assert normal.get("/api/v1/materials", headers=headers).json() == {"items": []}
                assert normal.get("/api/v1/reports", headers=headers).json() == {"items": []}
            assert len(demo.get("/api/v1/materials", headers=DEMO).json()["items"]) == 5


def test_fixture_totals_are_documented_scope_not_quarterly_attendance():
    def rows(case, filename):
        with (FIXTURES / case / filename).open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    snapshots = rows("technical-q2", "项目进度.csv")
    latest = {
        row["project_id"]: row for row in sorted(snapshots, key=lambda row: row["snapshot_date"])
    }
    assert len(snapshots) == 5 and len(latest) == 4
    assert sum(row["status"] == "completed" for row in latest.values()) == 2
    assert all(0 <= float(row["progress"]) <= 100 for row in snapshots)
    attendance = rows("technical-q2", "人员考勤.csv")
    assert len(attendance) == 4
    assert {row["date"] for row in attendance} == {"2026-06-29", "2026-06-30"}
    assert sum(float(row["planned_hours"]) for row in attendance) == 32
    assert sum(float(row["actual_hours"]) for row in attendance) == 28
    assert sum(float(row["leave_hours"]) for row in attendance) == 4
    feedback = rows("administration-q1", "满意度.csv")
    assert len(feedback) == 4
    assert {(row["scale_min"], row["scale_max"]) for row in feedback} == {("1", "5")}
    assert sum(float(row["score"]) for row in feedback) / len(feedback) == 4.0


def test_broken_case_validation_never_confirms_partial_materials(tmp_path):
    demo_root = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, demo_root)
    corrupt = demo_root / "technical-q2" / "成果统计.csv"
    corrupt.write_text(corrupt.read_text().replace("2026-06-25", "2026-06-99"))
    database = tmp_path / "app" / "workbench.sqlite3"
    with TestClient(create_app(database, static_dir=False, demo_root=demo_root)) as client:
        response = client.post("/api/v1/demo/load", headers=DEMO)
        assert response.status_code == 422
        assert client.get("/api/v1/materials", headers=DEMO).json() == {"items": []}
        assert client.get("/api/v1/materials").json() == {"items": []}
        # Fixing the same synthetic fixture permits one clean complete load.
        corrupt.write_text(corrupt.read_text().replace("2026-06-99", "2026-06-25"))
        recovered = client.post("/api/v1/demo/load", headers=DEMO)
        assert recovered.status_code == 200
        assert len(recovered.json()["materials"]) == 5
