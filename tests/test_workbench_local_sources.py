"""The ordinary application can explicitly freeze fixed local sample interfaces."""

from fastapi.testclient import TestClient

from office_agents.workbench import create_app


def test_normal_interface_import_is_explicit_frozen_and_workspace_scoped(tmp_path):
    with TestClient(create_app(tmp_path / "workbench.sqlite3", static_dir=False)) as client:
        source = client.get("/api/v1/data-sources/projects")
        assert source.status_code == 200
        assert source.json()["source"] == "local_sample_api"
        assert len(source.json()["records"]) == 36
        assert client.get("/api/v1/materials").json()["items"] == []
        draft = client.post("/api/v1/materials/from-local-api", json={"kind": "projects"})
        assert draft.status_code == 201
        draft = draft.json()
        assert draft["dataset_id"] == source.json()["dataset_id"]
        assert draft["source"] == "local_api" and draft["workspace"] == "normal"
        confirmed = client.post(
            f"/api/v1/imports/{draft['id']}/confirm",
            json={"mapping": draft["suggested_mapping"]},
        )
        assert confirmed.status_code == 200
        material = confirmed.json()
        assert len(client.get("/api/v1/materials").json()["items"]) == 1
        assert client.get("/api/v1/materials", headers={"X-Workspace": "demo"}).json() == {
            "items": []
        }
        assert (
            client.get(
                f"/api/v1/materials/{material['id']}", headers={"X-Workspace": "demo"}
            ).status_code
            == 404
        )
        assert client.get(f"/api/v1/materials/{material['id']}/download").content.startswith(
            b"project_id,department"
        )


def test_normal_interface_rejects_paths_urls_and_missing_sources(tmp_path):
    with TestClient(
        create_app(tmp_path / "db.sqlite3", static_dir=False, local_data_root=tmp_path / "missing")
    ) as client:
        assert client.get("/api/v1/data-sources/satisfaction").status_code == 503
        assert client.get("/api/v1/data-sources/unknown").status_code == 422
        for payload in [
            {"kind": "projects", "url": "https://example.invalid/data"},
            {"kind": "projects", "path": "/etc/passwd"},
        ]:
            assert client.post("/api/v1/materials/from-local-api", json=payload).status_code == 422
        assert client.get("/api/v1/materials").json()["items"] == []
