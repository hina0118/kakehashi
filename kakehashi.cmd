@echo off
chcp 65001 >nul
rem kakehashi を起動する（初回は依存関係の導入と画面のビルドも行う）
setlocal
cd /d "%~dp0"

where uv >nul 2>nul || (
  echo uv が見つかりません。https://docs.astral.sh/uv/ からインストールしてください。
  pause
  exit /b 1
)

if not exist ".venv" (
  echo 依存関係をインストールしています...
  uv sync --extra mcp || (pause & exit /b 1)
)

if not exist "frontend\dist\index.html" (
  where npm >nul 2>nul || (
    echo npm が見つかりません。Node.js をインストールしてください。
    pause
    exit /b 1
  )
  echo 画面をビルドしています...
  call npm --prefix frontend install || (pause & exit /b 1)
  call npm --prefix frontend run build || (pause & exit /b 1)
)

uv run kakehashi serve %*
