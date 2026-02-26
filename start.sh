#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if command -v uv &> /dev/null; then
    echo "[kakehashi] uv を使用します"
    uv sync
    uv run python main.py
else
    echo "[kakehashi] pip を使用します"
    if [ ! -d "venv" ]; then
        echo "[kakehashi] 仮想環境を作成しています..."
        python3 -m venv venv
    fi
    source venv/bin/activate
    pip install -q -r requirements.txt
    python main.py
fi
