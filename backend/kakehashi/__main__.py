"""kakehashi の起動コマンド。

    kakehashi serve   Web UI を起動してブラウザを開く
    kakehashi mcp     MCP サーバ（stdio）を起動する
"""
from __future__ import annotations

import argparse
import threading
import webbrowser


def main() -> None:
    parser = argparse.ArgumentParser(prog="kakehashi")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="Web UI を起動する")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--no-browser", action="store_true")
    serve.add_argument("--reload", action="store_true", help="開発用：コード変更で自動再起動")

    sub.add_parser("mcp", help="MCP サーバ（stdio）を起動する")

    args = parser.parse_args()
    if args.command == "mcp":
        from kakehashi.mcp.server import run
        run()
        return

    if args.command is None:
        args = serve.parse_args([])

    import uvicorn

    if not args.no_browser:
        url = f"http://{args.host}:{args.port}/"
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(
        "kakehashi.api.app:create_app", factory=True,
        host=args.host, port=args.port, reload=args.reload,
    )


if __name__ == "__main__":
    main()
