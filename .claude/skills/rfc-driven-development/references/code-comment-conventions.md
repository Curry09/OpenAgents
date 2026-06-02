# Code Comment Conventions

RFC ID referencing conventions for implementation code. All code should trace back to its RFC
design rationale. OpenAgents is a Python project, so examples below use Python syntax.

Language: comments may be English or Chinese — clarity over language choice (CLAUDE.md).
The key invariant is **consistent RFC ID referencing at every level**.

## 4 Comment Levels

### 1. Module-level docstring

At the top of each file, describe the module's purpose and its RFC reference.

```python
"""Agent 消息转告路由。

RFC-0007: Agent 消息转告机制

提供：
- 接收 Agent 间消息并包装为 User query
- 按目标 Agent 投递到其消息队列
"""
```

### 2. Function / class docstring

First line: short English summary. Second line: RFC reference. Then detail (Chinese ok):

```python
def relay_message(*, sender: str, target: str, text: str) -> None:
    """Relay a message from one agent to another.

    RFC-0007: 转告 A 给 B 的消息

    将 sender 的原文包装成 "A 给你发了一条：..." 的 User query，
    投递到 target 的消息队列。
    """
```

### 3. Inline step comments

Use numbered steps with short descriptions for each logic block:

```python
def relay_message(*, sender: str, target: str, text: str) -> None:
    # 1. 校验 target Agent 存在
    agent = _get_agent(name=target)

    # 2. 包装为 User query 形式
    query = f"{sender} 给你发了一条：{text}"

    # 3. 投递到 target 的消息队列
    _enqueue(agent=agent, query=query)
```

### 4. Field / attribute docs

Document dataclass fields / class attributes:

```python
@dataclass
class AgentState:
    # RFC-0002: Agent 背后接的 coding agent 类型（claude code / codex / nexau）
    backend: str
    # RFC-0002: 该 Agent 当前所在的 worktree 路径
    worktree: Path
```

## Summary

| Level | Content | Purpose |
|-------|---------|---------|
| Module | docstring + RFC ref | File-level overview |
| Function/Class | English summary + RFC ref + Chinese detail | API docs |
| Inline steps | `# N.` 描述 | Logic flow |
| Fields/Attributes | RFC ref + description | Data model docs |
