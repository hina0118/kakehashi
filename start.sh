#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 仮想環境がなければ作成
if [ ! -d "venv" ]; then
    echo "[kakehashi] 仮想環境を作成しています..."
    python3 -m venv venv
fi

# 仮想環境を有効化
source venv/bin/activate

# 依存ライブラリをインストール（不足分のみ）
pip install -q -r requirements.txt

# アプリを起動
python main.py
