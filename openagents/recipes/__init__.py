"""# Spec-0060/T6: recipes —— 编排层：每个 flow 只有控制流 + runtime.run_agent 调用，
无任何版本控制/远端/子进程直接调用。按 agent 的结构化裁决路由（顺序/循环/分支），
自己不做任何业务判断。本组只落 solve_issue 一条竖切；vigil/poll_comments/fleet 留后续批次。
"""
