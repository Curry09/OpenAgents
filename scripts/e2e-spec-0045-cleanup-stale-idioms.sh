#!/usr/bin/env bash
set -euo pipefail
# Spec-0045/T5：文档口径清理的成果测试——lint/格式/测试全绿 + 死口径 grep 归零。
uv run --extra dev ruff check openagents tests
uv run --extra dev ruff format --check openagents tests
uv run --extra dev pytest -q

echo "== 死口径 grep 归零校验 =="
# 已删符号绝不应再作为「当前实现」出现在代码/测试里。
! grep -rn "rebase_open_prs\|rebase\.CONFLICT_COMMENT" openagents tests
# indexheal.py 已删，openagents 源里不应再出现该模块名。
! grep -rn "indexheal" openagents
# sync-prs 命令已删，测试注释里不应再把它当活着的构造路径。
! grep -rn "sync-prs" tests
echo "ALL GREEN: 无残留死口径"
