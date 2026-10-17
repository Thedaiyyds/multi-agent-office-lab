"""Real SQLite API checks; no provider, credentials or model calls are needed."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from office_agents.config import Settings
from office_agents.workbench import create_app


def draft(**overrides):
    return {
        "title": "部门工作汇报",
        "department": "技术部",
        "start_date": "2026-04-01",
        "end_date": "2026-07-01",
        "focus": "",
        "sections": ["工作进展", "问题与计划"],
        **overrides,
    }


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "workbench.sqlite3")) as instance:
        yield instance


def test_empty_database_and_safe_system_info(client, monkeypatch):
    monkeypatch.setattr(
        Settings,
        "from_env",
        classmethod(
            lambda cls: Settings(
                base_url="https://private.example/v1", model="private-model", api_key="secret-value"
            )
        ),
    )
    assert client.get("/api/v1/health").json() == {
        "status": "ok",
        "version": "2.0.0",
    }
    assert client.get("/api/v1/reports").json() == {"items": []}
    info = client.get("/api/v1/system")
    assert info.json()["model_configured"] is True
    assert info.json()["capabilities"] == [
        "drafts",
        "workspace_isolation",
        "materials",
        "demo_materials",
        "statistics",
        "agent_execution",
        "local_data_sources",
        "report_revisions",
        "markdown_pdf_delivery",
    ]
    for private in ["secret-value", "private-model", "private.example"]:
        assert private not in info.text
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls: Settings()))
    assert client.get("/api/v1/system").json()["model_configured"] is False


def test_reports_survive_app_restart_and_normalize_fields(tmp_path):
    database = tmp_path / "persistent.sqlite3"
    with TestClient(create_app(database)) as first:
        response = first.post(
            "/api/v1/reports",
            json=draft(title="  部门工作汇报  ", sections=[" 工作进展 ", "问题与计划"]),
        )
        assert response.status_code == 201
        report = response.json()
    with TestClient(create_app(database)) as restarted:
        loaded = restarted.get(f"/api/v1/reports/{report['id']}").json()
        assert loaded == report
        assert loaded["title"] == "部门工作汇报"
        assert loaded["sections"] == ["工作进展", "问题与计划"]
        assert loaded["version"] == 1
        assert loaded["status"] == "draft"
        assert loaded["workspace"] == "normal"


def test_spaces_are_isolated_for_lists_reads_and_writes(client):
    normal = client.post("/api/v1/reports", json=draft()).json()
    demo_headers = {"X-Workspace": "demo"}
    assert client.get("/api/v1/reports", headers=demo_headers).json() == {"items": []}
    demo = client.post("/api/v1/reports", json=draft(), headers=demo_headers).json()
    assert demo["workspace"] == "demo"
    assert [row["id"] for row in client.get("/api/v1/reports").json()["items"]] == [normal["id"]]
    for report, headers in [(normal, demo_headers), (demo, {})]:
        url = f"/api/v1/reports/{report['id']}"
        assert client.get(url, headers=headers).status_code == 404
        assert (
            client.patch(
                url + "/draft", json=draft(expected_version=1), headers=headers
            ).status_code
            == 404
        )
    assert client.get("/api/v1/reports", headers={"X-Workspace": "other"}).status_code == 422


def test_optimistic_lock_preserves_concurrent_edit(client):
    report = client.post("/api/v1/reports", json=draft()).json()
    url = f"/api/v1/reports/{report['id']}/draft"
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(
                lambda title: client.patch(url, json=draft(title=title, expected_version=1)),
                ["第一处修改", "第二处修改"],
            )
        )
    assert sorted(response.status_code for response in responses) == [200, 409]
    winner = next(response.json() for response in responses if response.status_code == 200)
    assert winner["version"] == 2
    assert client.get(f"/api/v1/reports/{report['id']}").json() == winner
    assert client.patch(url, json=draft(expected_version=True)).status_code == 422


def test_idempotent_creation_survives_restart_and_is_scoped(tmp_path):
    database = tmp_path / "persistent.sqlite3"
    headers = {"Idempotency-Key": "repeat-request"}
    with TestClient(create_app(database)) as first:
        created = first.post("/api/v1/reports", json=draft(), headers=headers).json()
    with TestClient(create_app(database)) as restarted:
        assert restarted.post("/api/v1/reports", json=draft(), headers=headers).json() == created
        conflict = restarted.post("/api/v1/reports", json=draft(title="不同请求"), headers=headers)
        assert conflict.status_code == 409
        demo = restarted.post(
            "/api/v1/reports", json=draft(), headers={**headers, "X-Workspace": "demo"}
        ).json()
        assert demo["id"] != created["id"]
        assert len(restarted.get("/api/v1/reports").json()["items"]) == 1


def test_concurrent_idempotency_uses_database_constraint(client):
    with ThreadPoolExecutor(max_workers=2) as pool:
        reports = list(
            pool.map(
                lambda _: client.post(
                    "/api/v1/reports", json=draft(), headers={"Idempotency-Key": "double-click"}
                ).json(),
                range(2),
            )
        )
    assert reports[0] == reports[1]
    assert len(client.get("/api/v1/reports").json()["items"]) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"title": "  "},
        {"title": "字" * 161},
        {"department": ""},
        {"department": "字" * 81},
        {"start_date": "2026-04-31"},
        {"start_date": "2026-4-01"},
        {"start_date": "2026-W14-3"},
        {"start_date": "2026-04-01T00:00:00"},
        {"end_date": "2026-04-01"},
        {"end_date": "2026-03-31"},
        {"sections": []},
        {"sections": ["  "]},
        {"sections": ["工作", " 工作 "]},
        {"sections": ["字" * 101]},
        {"sections": [str(i) for i in range(21)]},
        {"focus": "字" * 4001},
        {"server_path": "/private/file"},
    ],
)
def test_invalid_requests_are_rejected_without_persisting(client, changes):
    assert client.post("/api/v1/reports", json=draft(**changes)).status_code == 422
    assert client.get("/api/v1/reports").json() == {"items": []}


def test_search_is_literal_parameterized_and_scoped(client):
    title = "100% 进展_记录"
    created = client.post("/api/v1/reports", json=draft(title=title)).json()
    client.post("/api/v1/reports", json=draft(title="其他报告"))
    for search in ["100%", "_记录", "技术部"]:
        items = client.get("/api/v1/reports", params={"search": search, "status": "draft"}).json()[
            "items"
        ]
        assert any(item["id"] == created["id"] for item in items)
    for search in ["' OR 1=1 --", "%其他", "_其他"]:
        assert client.get("/api/v1/reports", params={"search": search}).json() == {"items": []}
    assert client.get("/api/v1/reports", params={"status": "approved"}).json() == {"items": []}
    assert len(client.get("/api/v1/reports", params={"status": ""}).json()["items"]) == 2
    assert client.get("/api/v1/reports", params={"status": "invalid"}).status_code == 422


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "attacker.example"},
        {"Host": "localhost.attacker.example"},
        {"Origin": "https://attacker.example"},
        {"Origin": "null"},
        {"Origin": "http://localhost:9001"},
        {"Origin": "http://localhost:5173/evil"},
        {"Origin": "http://localhost.attacker.example:5173"},
        {"Sec-Fetch-Site": "cross-site"},
    ],
)
def test_remote_host_and_cross_site_writes_are_rejected(client, headers):
    assert client.post("/api/v1/reports", json=draft(), headers=headers).status_code == 403
    assert client.get("/api/v1/reports").json() == {"items": []}


@pytest.mark.parametrize(
    "origin",
    ["http://testserver", "http://localhost:5173", "http://127.0.0.1:5173", "http://[::1]:5173"],
)
def test_local_same_origin_and_vite_proxy_writes_are_allowed(client, origin):
    assert (
        client.post("/api/v1/reports", json=draft(), headers={"Origin": origin}).status_code == 201
    )


def test_frontend_spa_fallback_does_not_hide_api_or_missing_assets(tmp_path):
    static = tmp_path / "dist"
    static.mkdir()
    (static / "index.html").write_text("<html>工作台</html>", encoding="utf-8")
    (static / "app.js").write_text("console.log('app')", encoding="utf-8")
    with TestClient(create_app(tmp_path / "app.sqlite3", static)) as client:
        assert "工作台" in client.get("/").text
        assert "工作台" in client.get("/reports/new").text
        assert client.get("/app.js").status_code == 200
        assert client.get("/api/v1/missing").status_code == 404
        assert client.get("/missing.js").status_code == 404
        assert client.get("/assets/no-extension").status_code == 404
        assert client.get("/%2E%2E/private").status_code == 404


def test_default_database_uses_explicit_data_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_DATA_DIR", str(tmp_path / "chosen"))
    other = tmp_path / "unrelated-cwd"
    other.mkdir()
    monkeypatch.chdir(other)
    with TestClient(create_app()) as client:
        assert client.post("/api/v1/reports", json=draft()).status_code == 201
    assert (tmp_path / "chosen/workbench.sqlite3").exists()
    assert not (other / "outputs").exists()


def test_static_serving_can_be_disabled(tmp_path):
    with TestClient(create_app(tmp_path / "app.sqlite3", static_dir=False)) as client:
        assert client.get("/").status_code == 404
        assert client.get("/api/v1/health").status_code == 200
