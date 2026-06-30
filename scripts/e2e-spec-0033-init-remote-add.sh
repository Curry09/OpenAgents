#!/usr/bin/env bash
# Spec-0033 端到端测试启动脚本：openagents init 冷启动新建远端后自动 git remote add origin。
#
# hermetic——不调真实 gh / GitHub。两段：
#   1) 离线确定性验证（ruff lint/format + pytest，全程 mock）。
#   2) 冷启动走通：在临时非 git 目录里以 stub 掉的 create_repo 驱动
#      ensure_project(interactive=True)，断言收尾时本地 git config 的
#      remote.origin.url 与新建的 url 一致（证明 _bootstrap 已把远端写回本地）。
#
# 用法：
#   bash scripts/e2e-spec-0033-init-remote-add.sh
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

echo "==> [1/2] 离线确定性验证（lint + format + 单元测试）"
uv run --extra dev ruff check openagents/config.py tests/test_config.py
uv run --extra dev ruff format --check openagents/config.py tests/test_config.py
uv run --extra dev pytest tests/test_config.py -q

echo
echo "==> [2/2] 冷启动走通：stub create_repo 驱动 ensure_project(interactive=True)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

URL="https://github.com/acme/widget.git"
ACTUAL="$(cd "$TMP" && PYTHONPATH="$ROOT" URL="$URL" uv run --project "$ROOT" python - <<'PY'
import os
import subprocess
from unittest import mock

from openagents.config import ensure_project

url = os.environ["URL"]
answers = iter(["y", "y", "acme/widget", "y"])  # git init / 新建远端 / 仓库名 / 私有
with (
    mock.patch("builtins.input", lambda prompt="": next(answers)),
    mock.patch("openagents.github.create_repo", lambda *, name, private: url),
):
    ctx = ensure_project(interactive=True)
assert ctx.remote == url, ctx.remote
written = subprocess.run(
    ["git", "config", "--get", "remote.origin.url"],
    capture_output=True, text=True, check=True,
).stdout.strip()
print(written)
PY
)"

echo "  本地 remote.origin.url = $ACTUAL"
[ "$ACTUAL" = "$URL" ] \
  || { echo "✗ 冷启动后本地 remote.origin.url 未写入或不一致"; exit 1; }
echo "  ✓ 冷启动新建远端后 git config remote.origin.url 与新建 url 一致"

echo
echo "✓ Spec-0033 端到端通过：init 冷启动新建远端后自动 git remote add origin 闭环可用。"
