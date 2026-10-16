"""Local-only entry point for the report workbench."""

import argparse
from pathlib import Path

import uvicorn

from office_agents.workbench.api import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="启动汇报协作工作台（仅限本机）")
    parser.add_argument("--port", type=int, default=8520)
    parser.add_argument("--data-dir", type=Path, help="本地数据目录，默认 outputs/workbench")
    parser.add_argument("--api-only", action="store_true", help="仅启动 API，配合 Vite 开发服务器")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("端口必须在 1–65535 之间")
    root = Path(__file__).resolve().parents[3]
    static_dir = root / "frontend" / "dist"
    if not args.api_only and not (static_dir / "index.html").is_file():
        parser.error(
            "请先在项目根目录执行 npm --prefix frontend ci 和 npm --prefix frontend run build"
        )
    database = (args.data_dir.resolve() / "workbench.sqlite3") if args.data_dir else None
    app = create_app(database_path=database, static_dir=False if args.api_only else static_dir)
    uvicorn.run(app, host="127.0.0.1", port=args.port, workers=1)


if __name__ == "__main__":
    main()
