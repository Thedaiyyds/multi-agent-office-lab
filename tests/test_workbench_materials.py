"""Material imports exercise real files and SQLite; no external service is used."""

import io
import sqlite3
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest
from docx import Document
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from office_agents.workbench import materials

PROJECTS = (
    "项目编号,部门,生效日期,快照日期,状态,进度\n"
    "P1,技术部,2026-01-01,2026-04-01,进行中,30\n"
    "P1,技术部,2026-01-01,2026-05-01,已完成,100\n"
)
NOTES_SCOPE = {"department": "技术部", "start_date": "2026-04-01", "end_date": "2026-07-01"}


def build_client(tmp_path):
    @contextmanager
    def connection():
        db = sqlite3.connect(tmp_path / "materials.db", timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    app = FastAPI()
    router = materials.create_material_router(connection, tmp_path / "files", tmp_path / "demo")
    app.include_router(router)
    return TestClient(app), router.material_service


@pytest.fixture
def client(tmp_path):
    instance, _ = build_client(tmp_path)
    with instance:
        yield instance


def stage(client, data=PROJECTS, name="项目快照.csv", kind="projects", workspace="normal", **scope):
    return client.post(
        "/api/v1/materials/import",
        files={"file": (name, data)},
        data={"kind": kind, **scope},
        headers={"X-Workspace": workspace},
    )


def confirm(client, draft, workspace="normal", **values):
    return client.post(
        f"/api/v1/imports/{draft['id']}/confirm",
        json={"mapping": draft["suggested_mapping"], **values},
        headers={"X-Workspace": workspace},
    )


def docx_bytes(text="测试正文", rows=None):
    document = Document()
    document.add_paragraph(text)
    if rows:
        table = document.add_table(rows=0, cols=len(rows[0]))
        for cells in rows:
            for cell, value in zip(table.add_row().cells, cells):
                cell.text = value
    stream = io.BytesIO()
    document.save(stream)
    return stream.getvalue()


def rewrite_zip(data, replace=None, extra=None):
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as original, zipfile.ZipFile(output, "w") as edited:
        for entry in original.infolist():
            content = original.read(entry.filename)
            edited.writestr(entry, (replace or {}).get(entry.filename, content))
        for name, content in (extra or {}).items():
            edited.writestr(name, content)
    return output.getvalue()


def test_csv_mapping_full_confirmation_and_original_survive_restart(tmp_path):
    client, _ = build_client(tmp_path)
    draft = stage(client).json()
    assert draft["suggested_mapping"]["project_id"] == "项目编号"
    assert draft["preview"][1]["location"] == "行 3"
    assert draft["row_count"] == 2
    result = confirm(client, draft)
    assert result.status_code == 200, result.text
    material = result.json()
    assert material["version"] == 1
    assert material["sha256"] == draft["sha256"]
    assert "relative_path" not in material
    assert str(tmp_path) not in result.text
    restarted, _ = build_client(tmp_path)
    assert restarted.get(f"/api/v1/materials/{material['id']}").json() == material
    assert (
        restarted.get(f"/api/v1/materials/{material['id']}/download").content == PROJECTS.encode()
    )
    assert restarted.get("/api/v1/materials?search=项目&kind=projects").json()["items"] == [
        material
    ]
    assert restarted.get("/api/v1/materials?search=不存在").json()["items"] == []


def test_confirmation_is_idempotent_but_configuration_conflicts(client):
    draft = stage(client).json()
    first = confirm(client, draft).json()
    assert confirm(client, draft).json() == first
    assert confirm(client, draft, department="行政部").status_code == 409
    duplicate = stage(client, name="另一个名称.csv").json()
    assert confirm(client, duplicate).json() == first
    assert len(client.get("/api/v1/materials").json()["items"]) == 1
    # Mapping is part of immutable identity: an extra mapped field differs.
    edited = stage(client, data=PROJECTS.replace("30", "40")).json()
    second = confirm(client, edited).json()
    assert second["version"] == 2
    assert second["id"] != first["id"]
    assert client.get(f"/api/v1/materials/{first['id']}/download").content == PROJECTS.encode()


def test_search_matches_confirmed_department_and_keeps_workspace_boundary(client):
    draft = stage(client, **NOTES_SCOPE).json()
    material = confirm(client, draft).json()
    assert client.get("/api/v1/materials", params={"search": "技术部"}).json()["items"] == [
        material
    ]
    assert client.get("/api/v1/materials", params={"search": "行政部"}).json()["items"] == []
    assert (
        client.get(
            "/api/v1/materials", params={"search": "技术部"}, headers={"X-Workspace": "demo"}
        ).json()["items"]
        == []
    )


def test_concurrent_duplicate_confirmation_is_atomic(tmp_path):
    client, service = build_client(tmp_path)
    draft = stage(client).json()
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(
            workers.map(
                lambda _: service.confirm(
                    draft["id"], "normal", {"mapping": draft["suggested_mapping"]}
                ),
                range(2),
            )
        )
    assert results[0] == results[1]
    assert len(client.get("/api/v1/materials").json()["items"]) == 1


def test_workspaces_isolate_import_confirm_listing_detail_and_download(client):
    draft = stage(client, workspace="demo").json()
    assert confirm(client, draft).status_code == 404
    confirmed = confirm(client, draft, workspace="demo").json()
    assert client.get("/api/v1/materials").json()["items"] == []
    for tail in ("", "/download"):
        assert client.get(f"/api/v1/materials/{confirmed['id']}{tail}").status_code == 404
    assert (
        len(client.get("/api/v1/materials", headers={"X-Workspace": "demo"}).json()["items"]) == 1
    )
    assert stage(client, workspace="invalid").status_code == 422


@pytest.mark.parametrize(
    "data,name,kind",
    [
        (b"hello", "../notes.txt", "notes"),
        (b"hello", "notes.pdf", "notes"),
        (b"PK\x00binary", "notes.txt", "notes"),
        (b"not zip", "notes.docx", "notes"),
        (b"", "notes.txt", "notes"),
    ],
)
def test_unsafe_and_unrecognized_inputs_never_stage(client, data, name, kind):
    assert stage(client, data, name, kind).status_code in {413, 422}
    assert client.get("/api/v1/materials").json()["items"] == []


def test_chinese_gb18030_text_and_multiline_physical_csv_locations(client):
    response = stage(client, "项目协调记录".encode("gb18030"), "工作记录.TXT", "notes")
    draft = response.json()
    assert draft["preview"][0]["values"]["text"] == "项目协调记录"
    assert confirm(client, draft).status_code == 422
    assert confirm(client, draft, **NOTES_SCOPE).status_code == 200
    multiline = PROJECTS.replace("进行中", '"进行\n中"')
    assert stage(client, multiline).json()["preview"][0]["location"] == "行 2–3"


def test_csv_malformed_row_and_error_beyond_preview_are_atomic(client):
    lines = ["person_id,department,date,planned_hours,actual_hours"]
    lines.extend(f"E{i},技术部,2026-04-01,8,8" for i in range(25))
    lines.append("E26,技术部,2026-02-30,8,-1")
    draft = stage(client, "\n".join(lines), "考勤.csv", "attendance").json()
    assert len(draft["preview"]) == 20
    result = confirm(client, draft)
    assert result.status_code == 422
    assert all(i["location"] == "行 27" for i in result.json()["detail"]["issues"])
    assert client.get("/api/v1/materials").json()["items"] == []
    broken = stage(client, PROJECTS + "P2,missing\n").json()
    assert broken["issues"][0]["location"] == "行 4"
    assert confirm(client, broken).status_code == 422


@pytest.mark.parametrize(
    "data,kind",
    [
        (PROJECTS + "P1,技术部,2026-01-01,2026-04-01,进行中,30\n", "projects"),
        (
            "person_id,department,date,planned_hours,actual_hours\nE1,技术部,2026-04-01,8,8\nE1,技术部,2026-04-01,8,7\n",
            "attendance",
        ),
        (
            "achievement_id,department,date,category,name\nA1,技术部,2026-04-01,交付,完成\nA1,技术部,2026-04-02,交付,完成\n",
            "achievements",
        ),
        (
            "feedback_id,department,date,score,scale_min,scale_max\nF1,行政部,2026-01-01,6,1,5\n",
            "satisfaction",
        ),
    ],
)
def test_duplicate_business_keys_and_invalid_scale_are_rejected(client, data, kind):
    draft = stage(client, data, "材料.csv", kind).json()
    assert confirm(client, draft).status_code == 422


def test_missing_attendance_stays_unknown_and_multiple_days_are_valid(client):
    data = (
        "person_id,department,date,planned_hours,actual_hours\n"
        "E1,技术部,2026-04-01,8,\nE1,技术部,2026-04-02,8,8\n"
    )
    draft = stage(client, data, "考勤.csv", "attendance").json()
    result = confirm(client, draft)
    assert result.status_code == 200
    assert result.json()["issues"][0]["severity"] == "warning"
    assert result.json()["preview"][0]["values"]["actual_hours"] == ""


def test_docx_paragraph_table_provenance_and_chinese_filename(client):
    text = stage(client, docx_bytes(), "工作记录.docx", "notes").json()
    assert text["preview"][0]["location"] == "段落 1"
    assert confirm(client, text, **NOTES_SCOPE).status_code == 200
    data = docx_bytes(rows=[row.split(",") for row in PROJECTS.strip().splitlines()])
    draft = stage(client, data, "部门项目.docx").json()
    assert draft["preview"][0]["location"] == "表格 1 / 行 2"
    assert confirm(client, draft).status_code == 200


@pytest.mark.parametrize(
    "extra",
    [
        {"../escape.xml": b"<x/>"},
        {"word/vbaProject.bin": b"macro"},
        {"word/embeddings/file.bin": b"embedded"},
    ],
)
def test_docx_traversal_macro_and_unsupported_embedded_files_rejected(client, extra):
    data = rewrite_zip(docx_bytes(), extra=extra)
    assert stage(client, data, "不安全.docx", "notes").status_code == 422


def test_docx_external_relationship_and_fake_zip_rejected(client):
    relationship = (
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        b'<Relationship Id="x" TargetMode="External" Target="https://example.invalid" '
        b'Type="hyperlink"/></Relationships>'
    )
    linked = rewrite_zip(docx_bytes(), replace={"word/_rels/document.xml.rels": relationship})
    assert stage(client, linked, "链接.docx", "notes").status_code == 422
    fake = io.BytesIO()
    with zipfile.ZipFile(fake, "w") as archive:
        archive.writestr("word/document.xml", "<x/>")
    assert stage(client, fake.getvalue(), "伪装.docx", "notes").status_code == 422
    malformed = rewrite_zip(docx_bytes(), replace={"word/document.xml": b"<document/>"})
    assert stage(client, malformed, "无正文.docx", "notes").status_code == 422


def test_all_resource_limits_are_enforced_without_partial_confirmation(client, monkeypatch):
    monkeypatch.setattr(materials, "MAX_BYTES", 10)
    assert stage(client, b"a" * 11, "large.txt", "notes").status_code == 413
    monkeypatch.setattr(materials, "MAX_BYTES", 10 * 1024 * 1024)
    monkeypatch.setattr(materials, "MAX_ROWS", 1)
    assert stage(client).status_code == 422
    monkeypatch.setattr(materials, "MAX_DOCX_BYTES", 100)
    assert stage(client, docx_bytes(), "large.docx", "notes").status_code == 422


def test_shared_service_restricts_demo_sources_and_never_accepts_external_urls(tmp_path):
    _, service = build_client(tmp_path)
    with pytest.raises(HTTPException) as error:
        service.stage_import(PROJECTS.encode(), "demo.csv", "projects", "normal", "demo")
    assert error.value.status_code == 403
    draft = service.stage_import(PROJECTS.encode(), "demo.csv", "projects", "demo", "local_api")
    material = service.confirm(draft["id"], "demo", {"mapping": draft["suggested_mapping"]})
    assert material["source"] == "local_api"
    assert service.original_path(service.get(material["id"], "demo")).is_file()


def test_storage_paths_cannot_escape_via_tampered_database_or_symlink(tmp_path):
    client, service = build_client(tmp_path)
    material = confirm(client, stage(client).json()).json()
    row = service.get(material["id"], "normal")
    row["relative_path"] = "../../../outside"
    with pytest.raises(HTTPException):
        service.original_path(row)
    (tmp_path / "files" / "demo").symlink_to(tmp_path)
    with pytest.raises(HTTPException):
        service.stage_import(PROJECTS.encode(), "demo.csv", "projects", "demo")


def test_preview_truncates_only_preview_original_text_remains(client):
    raw = ("记录" * 1000).encode()
    draft = stage(client, raw, "长记录.txt", "notes").json()
    assert len(draft["preview"][0]["values"]["text"]) == 1000
    material = confirm(client, draft, **NOTES_SCOPE).json()
    assert client.get(f"/api/v1/materials/{material['id']}/download").content == raw


def test_optional_completion_and_attendance_fields_are_suggested_and_validated(client):
    data = (
        PROJECTS.replace("状态,进度", "状态,进度,实际完成日期")
        .replace("进行中,30\n", "进行中,30,\n")
        .replace("已完成,100\n", "已完成,100,2026-05-01\n")
    )
    draft = stage(client, data).json()
    assert draft["suggested_mapping"]["completed_date"] == "实际完成日期"
    assert confirm(client, draft).status_code == 200
    invalid = stage(client, data.replace("100,2026-05-01", "100,2026-02-30")).json()
    assert confirm(client, invalid).status_code == 422
    attendance = (
        "person_id,department,date,planned_hours,actual_hours,请假工时,缺勤工时,迟到分钟\n"
        "E1,技术部,2026-04-01,8,6,2,0,10\n"
    )
    draft = stage(client, attendance, "考勤.csv", "attendance").json()
    assert set(draft["suggested_mapping"]) >= {"leave_hours", "absent_hours", "late_minutes"}
    assert confirm(client, draft).status_code == 200
    invalid = stage(
        client, attendance.replace(",2,0,10", ",2,0,-1"), "考勤.csv", "attendance"
    ).json()
    assert confirm(client, invalid).status_code == 422


@pytest.mark.parametrize(
    "flag,code", [("true", 200), ("false", 200), ("1", 200), ("0", 200), ("maybe", 422)]
)
def test_optional_satisfaction_valid_marker_is_preserved(client, flag, code):
    data = (
        "feedback_id,department,date,score,scale_min,scale_max,有效标记\n"
        f"F1,行政部,2026-01-01,4,1,5,{flag}\n"
    )
    draft = stage(client, data, "满意度.csv", "satisfaction").json()
    assert draft["suggested_mapping"]["valid"] == "有效标记"
    assert confirm(client, draft).status_code == code


def test_docx_notes_limit_counts_paragraphs_and_table_rows_together(client, monkeypatch):
    monkeypatch.setattr(materials, "MAX_ROWS", 2)
    data = docx_bytes(text="正文", rows=[["表头"], ["记录"]])
    assert stage(client, data, "超行数.docx", "notes").status_code == 422
    assert client.get("/api/v1/materials").json()["items"] == []


def test_read_only_preflight_uses_confirmation_rules_without_writing(tmp_path):
    client, service = build_client(tmp_path)
    good = stage(client).json()
    bad = stage(client, PROJECTS.replace("100", "120")).json()
    request = {"mapping": good["suggested_mapping"]}
    assert service.validate_import(good["id"], "normal", request) == []
    issues = service.validate_import(bad["id"], "normal", request)
    assert issues[0]["location"] == "行 3"
    assert issues[0]["severity"] == "error"
    assert client.get("/api/v1/materials").json()["items"] == []
    confirmed_issues = confirm(client, bad).json()["detail"]["issues"]
    assert issues == confirmed_issues
    with pytest.raises(HTTPException) as error:
        service.validate_import(good["id"], "demo", request)
    assert error.value.status_code == 404
    assert confirm(client, good).status_code == 200
    assert service.validate_import(good["id"], "normal", request) == []
    with pytest.raises(HTTPException) as error:
        service.validate_import(good["id"], "normal", {**request, "department": "changed"})
    assert error.value.status_code == 409
