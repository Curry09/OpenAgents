"""# Spec-0061/T1: utils.notes —— PR/issue 评论正文渲染的稳定 import 面（纯函数、零 IO）。

把三个便签渲染模块（blocknote 挂起便签 / worknote 自述回执 / replynote 引用回复）的纯渲染
函数收敛到一个 utils 命名空间，供 recipes.poll_comments 组织回复正文、recipes.vigil 组织挂起
便签用。这些是**确定性纯函数**（无 IO、无判断），归 utils 而非 agent——文案模板不是「需要判断」
的操作。薄再导出，不复制、不改动三个源模块任何一行。

命名空间前缀化避免三源同名冲突：blocknote.build → build_block；replynote.build → build_reply；
worknote.render_* 原样透传（名字本已含区分）。
"""

from __future__ import annotations

# Spec-0061/T1: 再导出三个便签渲染纯函数（前缀化消歧），不改源模块。
from openagents.blocknote import build as build_block
from openagents.blocknote import build_hold_merge_pass
from openagents.replynote import build as build_reply
from openagents.worknote import render_implement, render_iterate

__all__ = [
    "build_block",
    "build_hold_merge_pass",
    "build_reply",
    "render_implement",
    "render_iterate",
]
