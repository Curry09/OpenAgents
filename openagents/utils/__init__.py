"""# Spec-0060/T1: utils —— 所有确定性、非 agent 的原语的归口包。

本包只作命名空间标记；下游按需分模块导入（`from openagents.utils import git, github`），
不在 __init__ 里做重导出，避免 __init__ 成为跨 Task/跨模块的共写点（理念 10 解耦）。
本批次（批次一）只立起 solve_issue recipe 依赖的最小面：git（worktree 生命周期 + 只读原语）、
github（gh 读 + 机器评论写）。旧模块整体搬进 utils/ 及 release/notes/spec 归位留后续批次。
"""
