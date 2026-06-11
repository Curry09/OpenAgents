# Code Comment Conventions

Spec id referencing conventions for implementation code. All new code should trace back to its
spec design rationale. OpenAgents is a Python project, so examples use Python syntax.

Language: comments may be English or Chinese — clarity over language choice (CLAUDE.md).
The key invariant is **consistent spec id referencing at every level**.

## Spec id format & grandfathering (RFC-0014 D11/D12)

- New code uses `# Spec-NNNN/Tn: …` (group number + Task id), e.g. `# Spec-0014/T3: …`.
- Existing `# RFC-NNNN` comments are **grandfathered, not rewritten** — spec group `NNNN`
  is 1:1 with old RFC `NNNN`, so `RFC-0007` ≡ `Spec-0007`. Don't mass-rewrite them.

## 4 Comment Levels

### 1. Module-level docstring

```python
"""Agent 消息转告路由。

Spec-0007/T2: Agent 消息转告机制

提供：接收 Agent 间消息并包装为 User query；按目标 Agent 投递到其消息队列。
"""
```

### 2. Function / class docstring

First line: short English summary. Second line: spec reference. Then detail (Chinese ok):

```python
def relay_message(*, sender: str, target: str, text: str) -> None:
    """Relay a message from one agent to another.

    Spec-0007/T2: 转告 A 给 B 的消息

    将 sender 的原文包装成 "A 给你发了一条：..." 的 User query，投递到 target 的消息队列。
    """
```

### 3. Inline step comments

```python
    # 1. 校验 target Agent 存在
    agent = _get_agent(name=target)
    # 2. 包装为 User query 形式
    query = f"{sender} 给你发了一条：{text}"
```

### 4. Field / attribute docs

```python
@dataclass
class AgentState:
    # Spec-0002/T1: Agent 背后接的 coding agent 类型（claude code / codex / nexau）
    backend: str
```

## Summary

| Level | Content | Purpose |
|-------|---------|---------|
| Module | docstring + spec ref | File-level overview |
| Function/Class | English summary + spec ref + Chinese detail | API docs |
| Inline steps | `# N.` 描述 | Logic flow |
| Fields/Attributes | spec ref + description | Data model docs |
