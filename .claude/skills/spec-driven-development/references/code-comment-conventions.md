# Code Comment Conventions

Write comments and docstrings in English. Use `Spec-NNNN/Tn` to link code to its design task.
Older `RFC-NNNN` references still identify the same numbered group; preserve them unless the
underlying reference changes.

- Put a module's Spec reference in a file-level comment. Start the module docstring with a short
  English summary ending in a period, then a blank line, usage examples where useful, and an
  `Exports:` list. For packages, also list exported modules and subpackages.
- Start function and class docstrings with an imperative summary of at most 80 characters ending
  in a period. Add the Spec reference on the next line. Use `Args:`, `Returns:`, and `Raises:`
  when they clarify the interface.
- Explain decisions, ordering constraints, and invariants in inline comments. Avoid restating
  self-explanatory code.

```python
# Spec-0007/T2
"""Route a message to another agent.

Exports:
    relay_message: Enqueue a message for the destination agent.
"""

def relay_message(*, target: str, text: str) -> None:
    """Enqueue a message for the destination agent.
    Spec-0007/T2.
    """
    agent = _get_agent(name=target)
    agent.queue.put(text)
```
