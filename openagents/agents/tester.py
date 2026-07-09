"""# Spec-0060/T4: agents.tester —— 独立 e2e 执行 + 判读的提示词（零逻辑）。

文案从旧 executor.py 的独立执行 + 判读串降为 prompt 字符串。e2e 结果如何判读是「需要判断」的
操作，故下放 agent 出结构化裁决；本组 solve_issue recipe 暂不串 tester（e2e 由 PR signpost/
后续批次采集），但模块随 5 agent 一并立起，供后续 recipe 复用。
"""

from string import Template

PROMPT = Template(
    """你是独立测试 agent。对 PR #$pr_number 按其 spec 的 e2e 测法块（frontmatter 的 intent + method）真正执行成果测试并判读：
- 按 method 描述真跑（浏览器导航/截图断言，或离线确定性脚本，视工具与改动类别而定）；
- 产品对外行为必须有真 app 证据，纯内部改动相称自动化测试即可；不许拿「慢/flaky」当跳过借口，真跑不起来就诚实判 REWORK 并写清阻塞原因。

裁决二选一：证据充分且通过 → PASS；未跑通/证据不足/有失败 → REWORK。
最后只输出一行 JSON：{"verdict": "PASS" 或 "REWORK", "reason": "<判读理由，含证据落点>"}

issue 原文：
$issue_body
"""
)

OUTPUT_SCHEMA = {"verdict": str, "reason": str}
