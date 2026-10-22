"""Import the published synthetic files through the existing material API, without duplicates."""

import argparse
import hashlib
import json
from pathlib import Path

import httpx


def import_files(client, root):
    root = Path(root)
    manifest = json.loads((root / "manifest.json").read_text())
    response = client.get("/api/v1/materials")
    response.raise_for_status()

    def identity(item):
        return tuple(
            item[key] for key in ("sha256", "kind", "department", "start_date", "end_date")
        )

    existing = {identity(item) for item in response.json()["items"]}
    imported = skipped = 0
    for item in manifest["files"]:
        if identity(item) in existing:
            skipped += 1
            continue
        path = (root / item["path"]).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("Manifest file must be inside the dataset directory")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise ValueError("Source hash changed: " + item["name"])
        response = client.post(
            "/api/v1/materials/import",
            data={key: item[key] for key in ("kind", "department", "start_date", "end_date")},
            files={"file": (item["name"], raw)},
        )
        response.raise_for_status()
        draft = response.json()
        response = client.post(
            f"/api/v1/imports/{draft['id']}/confirm",
            json={"mapping": draft["suggested_mapping"]},
        )
        response.raise_for_status()
        existing.add(identity(response.json()))
        imported += 1
    return dict(imported=imported, skipped=skipped)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8520")
    args = parser.parse_args()
    url = httpx.URL(args.url)
    if url.host not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("This synthetic dataset importer only targets the local workbench")
    with httpx.Client(base_url=args.url, trust_env=False, timeout=60) as client:
        print(json.dumps(import_files(client, Path(__file__).resolve().parent)))
