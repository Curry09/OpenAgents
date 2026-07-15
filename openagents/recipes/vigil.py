"""# Spec-0065/T2: recipes.vigil —— 图驱动的并行守夜 `run_vigil`（**level-triggered reconcile**，K=1 即串行）。

本文件是旧串行守夜的深模块化重写（旧实现已随本次重写删除——git history 是唯一回退点，不留死代码副本）。
**只一个入口 `run_vigil`、只一个文件**：守夜天生按「subject 为并发单元」调度，`concurrency`(=K) 是并发
上限；**串行不是另一种模式，而是 `concurrency=1` 的退化**。故不拆 serial/parallel 两函数两文件——那是把
同一件事摊成浅模块（Ousterhout：深模块 = 简单接口 + 大量功能，https://milkov.tech/assets/psd.pdf）。

## 感知模型：level-triggered，不做变更检测

谓词**无历史**：不问「跟上一轮比变了没」，只问「现在该不该动手」。每 tick 对每个 subject 重算，丢一轮丢
一百轮都能自愈。这是 Kubernetes 的架构第一原则，原文：*"Functionality must be level-based, meaning the
system must operate correctly given the desired state and the current/observed state, **regardless of how
many intermediate state updates may have been missed**. Edge-triggered behavior must be just an
optimization."*
(https://github.com/kubernetes/design-proposals-archive/blob/main/architecture/principles.md)

**为什么不能靠「记住上一轮状态、变了就叫 agent」**：进程崩在「检测到 CI 变绿」和「真的去合并」之间，
那个边沿就永久消失了——PR 会绿着躺到宇宙热寂。而漏一个边沿 = 一个 PR 永久停摆。

三个纯函数吃**同一个**不可变结构，这是本文件的骨架：

    observed = _sense(subject)                          # 唯一的副作用：读一次 GitHub
    verdict  = _classify(observed.facts, in_flight=…)   # 纯函数 → 四值判定
    fp       = _fingerprint(observed.facts)             # 纯函数 → 哈希

（`in_flight` = 「队列里有该 subject 的 claimed 行」，是唯一非-GitHub 的输入，由调用侧喂。**生产者**据实传；
**worker 恒传 `False`**——它自己就是那个 in-flight 的持有者，传 True 会让每个 worker 领到活就判「有人在干」
并立刻收工，系统一动不动。见 `_classify`。）

**不变式：`_fingerprint` 的字段集 ≡ `_classify` 的输入字段集 ≡ `_Facts` 的全部字段。** 二者吃同一个
frozen dataclass，结构上不可能漂移。`_Clock`（时间戳）**绝不进 fp**——一个 check run 开始跑会刷新
`started_at`，若混进 fp 就会把 agent 反复叫起，而分支表根本不看这个字段。

**三态 `skip` 在 `_sense` 里归一成「事实上已过闸」**（`OWNER_SKIP` = 不设此闸、当 PASS 放行）：`ci: skip`
→ facts.ci 记 success，`e2e: skip` → 证据戳记当前 head，`review: skip` → 裁决记 APPROVED@head。这样
`_classify` 保持**纯粹的机械分支表**、不需要吃 config，而「闸归谁」的策略只在两处出现：`_sense`（skip）
与 `_act`（agent / human）。

## 收口：主路径是 agent 自己打 `needs-human`，护栏只兜它看不见的三种死法

**agent 干不动时的正常收口是它自己打 `needs-human`**（一等出口，不是快路径、不是脚注）：CI 是上游 flaky、
需求本身有歧义、要动的东西超出授权——它打 label + 留一条说明理由的评论，`_classify` 分支①当场判 TERMINAL，
**轮询立刻停止**。不烧多余的 LLM 调用、不等任何超时、理由直接写在 issue 上给人看。人摘掉 label，谓词自动
重新活过来（level-triggered 白送的自愈）。这条契约必须写进每个分支的 agent 提示词。

**只有 agent 自己看不见的死法才需要护栏。** level-triggered 自带三个，共同点是**在日志里跟「一切正常」长得
一模一样**：

1. **agent 没意识到自己在空转**——它以为干了活（rerun 了 CI 但没触发、改了个无关文件、发条「等 CI 重跑就
   好」的评论就收工），所以**不会**去打 `needs-human`；而它每轮留的评论还会刷新时间戳，**看门狗也永远不
   响**。除了机械比对，没有任何东西拦得住它无限重跑、无限烧钱。护栏 = worker 零进展收工时盖一条**带 `fp`
   的 attempt 戳**（签名评论）；生产者见到 fp 相同的戳，就把 ACTIONABLE 降级为 `QUIET(awaiting-effect)`、
   不入队。记忆存 **GitHub**。`fp` 没变 ⟺ 分支表关心的每个字段都没动 ⟺ **零进展**——agent 怎么说的不算数。
   故只需**一个 bit**（有/无），不需要计数。（**盖戳本身必须不改 fp**，否则这道护栏会自毁成死循环：见
   `_Facts` 为什么不含 comment id。）
2. **状态该动却不动**（CI 永不启动：workflow 没匹配 / base 不是 main / Actions 被禁 → 谁都不叫 agent →
   PR 静默烂掉，日志里跟「正常等 CI」长得一模一样）。这里连 agent 都没被叫起，自然不可能自己打 label。
   护栏 = **看门狗**：QUIET 的 age 超阈值 → 打 `needs-human` + 贴机械诊断。而「卡了多久」是**当前态的纯
   函数**——每个 GitHub 对象都自带时间戳，`age = now − last_progress_at`。**零本地记忆**：重启、丢库、换
   机器都不影响。
3. **agent 没能收工**（崩溃 / 被 kill / 挂死在一个不返回的调用上）——它在 GitHub 上**不留任何痕迹**：既没
   打 label、没盖戳、也没刷新任何时间戳。fp 判不出来，age 也判不出来。崩溃由 `flock` 判死（§6.1），挂死由
   `_act` 的硬超时（`_AGENT_TIMEOUT_SECONDS`）+ IN_FLIGHT 告警（`_INFLIGHT_ALARM_SECONDS`）兜；反复领取
   不收工则由 `work_queue.attempts` 计数收口——**这是唯一必须计数的死法**。

三道护栏与主路径**同一个收尾**：`needs-human` → TERMINAL → 轮询停止。区别只在**谁**打的这个 label。

## 存储职责：两个存储，各管一层，无重叠

- **GitHub** = 领域真相：依赖结构（原生 `blocked_by`）+ 我们做的**决定**（label：`ready` 准入 /
  `needs-human` 终态 / `review-approved:<sha7>` 裁决）+ GitHub 自己维护的**事实**（checks / mergeable，
  读原生、**不复制成 label**）+ e2e 证据评论 + **已出手过的状态**（attempt 戳）。

  **分界线：决定打 label，事实读原生。** 「人来接手」「审过了」GitHub 没有别的地方表达，故落 label；
  「CI 绿不绿」它自己就绑在 sha 上、一次读到，再复制一份成 label 就是造第二份真相，然后要负责让两份不打架
  （CI 重跑了谁去改 label？）。而 review 裁决落 label 时**必须把 head sha 带进 label 名**——裁决绑 commit，
  光秃秃的 `review-approved` 会在 agent 审后又 push 时留在原地 → **合并一份没人审过的代码**，且不可逆。
- **SQLite `work_queue`** = 只存 GitHub **表达不了**的三样：①谁原子地领走了这个 subject ②领了几次没收工
  ③领取时的定序。**丢了无害**——`queued` 行一 tick 从 GitHub 重建，`claimed` 行由 `_reclaim_dead` 凭 flock
  回收。
- **`claims/{subject}.lock`（flock）** = 持有者的**存活证明**，由内核持有：进程一死，锁自动释放。

**为什么认领必须落 DB、而不能用 GitHub label。** GitHub REST 对不安全方法**不支持条件请求**（原文：
*"Conditional requests for unsafe methods, such as POST, PUT, PATCH, and DELETE are not supported unless
otherwise noted."*），且 label POST 是**追加**语义——两个并发认领**都会成功、都不报错**。即无 CAS。
`runtime/state.py` 的整文件 JSON 读改写同样会丢更新（#137 明列的「State 并发写」风险）。DB 事务根治。
(https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api)

## 队列形态：一行 = 一个 subject

`subject` 列 **UNIQUE**，一根柱子同时扛三件事：**幂等入队**（每 tick 无脑 `INSERT OR IGNORE`，重复是
no-op）、**同-subject 串行**（一个 subject 最多一行 → 同一个 PR 上永远只有一个 agent）、**去重**。故
`_claim_next` **不需要** `NOT EXISTS` 同-subject 子查询——互斥已在**入队时**结构性保证。

对标 Multica 的 `agent_task_queue`：`ClaimAgentTask`（`UPDATE … WHERE id=(SELECT … FOR UPDATE SKIP
LOCKED) RETURNING *`）+ `MaxConcurrentTasks` slot 背压。差异：Multica 是**多 daemon 进程**领同一队列故须
Postgres；本仓是**单机 K 线程**，SQLite `BEGIN IMMEDIATE`（立刻取写锁、序列化并发写；抢不到走
`busy_timeout` 重试）是 `SKIP LOCKED` 的单机等价物，零外部依赖。**且本仓不用租约**：死亡不靠猜（见下）。

## 回收：凭 flock 判死，不凭租约猜死

认领时对 `.openagents/claims/{subject}.lock` 取一把 `fcntl.flock(LOCK_EX | LOCK_NB)`，**持到收工**。flock
绑在**打开文件描述**上，**进程一死内核自动释放**（`kill -9` / OOM / 段错误 / 断电全算）。于是回收判据变成
一次无阻塞抢锁：抢得到 ⇒ 内核已回收持有者的锁 ⇒ 它**确已死** → 行立刻回 `queued`；抢不到（EWOULDBLOCK）
⇒ 持有者**确实活着** → **永不回收**（无论它跑了多久）。**双跑是结构性的零，不是小概率**；`_reclaim_dead`
没有任何阈值参数，也就没有任何可以调错的旋钮。

**必须是 flock，不能是 `fcntl.lockf`（POSIX `F_SETLK`）**：后者的锁是 **per-process** 的，同一进程内两个
fd 对同一文件加锁**不互斥**——而本模块是「一个进程 K 条 worker 线程」，用 `lockf` 会让互斥**静默失效**。

**收工必须先删行、再 `close(fd)`**（`_mark_done` / `_requeue_or_park` 同理）。反过来会开一个窗口：锁已放、
行还挂着 `claimed` → 另一个 `_reclaim_dead` 抢到锁、判「死了」、把行打回 `queued` → 被重领 → **双跑**。

「活着但卡死」是另一件事（flock 只回答**存在**）：由 `_act` 的硬超时（超时杀子进程 + 抛出，持有者自己
`_requeue_or_park` 释放行与锁）+ IN_FLIGHT 看门狗（超龄只 `_park` 打 needs-human，**绝不动行**）兜。

**SQLite 与 flock 同把部署钉在单机。** sqlite.org 明文禁止跨网络文件系统共享同一个库，而且是**数据损坏**
级别：*"file locking logic is buggy in many network filesystem implementations… resulting in corruption."*
（https://www.sqlite.org/whentouse.html ; https://www.sqlite.org/useovernet.html）；NFS 上 flock 被模拟成
`fcntl` 字节范围锁，「同进程多 fd 互斥」这条我们赖以成立的性质会静默失效——**两者是同一条边界**。多机时的
替换点收在 4 个函数里：`_claim_next` / `_reclaim_dead` / `_mark_done` / `_requeue_or_park`（GitHub 恰好有
真 CAS：`POST /git/refs` ref 已存在则 422）。**本版不预先建这个抽象**（奥卡姆：不为「可能」付费）。
- SQLite WAL：https://www.sqlite.org/wal.html ；`RETURNING`：https://www.sqlite.org/lang_returning.html
- Postgres `SKIP LOCKED`：https://www.postgresql.org/docs/current/sql-select.html
- Airflow pools（K 槽限并发 + priority 在可运行集内定序）：
  https://airflow.apache.org/docs/apache-airflow/stable/administration-and-deployment/pools.html

依赖（backend / github / git / engine / stages）仍可注入或 monkeypatch，hermetic 可测。
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import sqlite3
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, fields, replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from openagents.agents import curator, replier, tester
from openagents.recipes import stages
from openagents.runtime import context, engine, timing
from openagents.runtime.state import RuntimeState
from openagents.utils import agent_config, git, github, identity, proc

# Spec-0065/T2: 单 issue → 单分支命名（承旧串行 vigil 一致）。
_BRANCH_PREFIX = "openagents/issue-"

# Spec-0065/T2: 队列 DB 文件名——独立命名空间（与 runtime-state.json 同置 .openagents/，文件级零冲突）。
_QUEUE_DB_FILENAME = "vigil-queue.db"

# Spec-0065/T2: 存活证明的锁文件目录（`.openagents/claims/{subject}.lock`）。锁由**内核**持有，进程一死
# 自动释放——这就是「判死」的全部机制（不猜、不设阈值、不用租约）。
_CLAIMS_DIRNAME = "claims"

# Spec-0065/T2: 单次 `_act`（一次 agent 调用）的硬墙钟上限（秒）。超它 → 杀掉该 agent 的子进程 + 抛出 →
# 持有者自己走 `_requeue_or_park` 释放行与锁（**claimed 行永不成孤儿**）。flock 只回答「进程在不在」，
# 回答不了「进程活着但挂死在一个不返回的调用上」——那要靠这道闸。
_AGENT_TIMEOUT_SECONDS = 1800

# Spec-0065/T2: IN_FLIGHT 告警阈值（秒）：claimed 行的 `claimed_at` 超龄 → `_park`（打 needs-human + 诊断）。
# **只告警、绝不回收行**——回收一个活着的持有者的行，定义上就是双跑。
_INFLIGHT_ALARM_SECONDS = 7200

# Spec-0065/T2: 同一 subject 领取-失败重排上限；超它不再回队、打 needs-human 交人。
# **这是唯一必须计数的护栏**——agent 崩/被 kill 时它没盖 attempt 戳、也没刷新任何 GitHub 时间戳，
# 在 GitHub 上零痕迹：fp 判不出、age 也判不出，只能在队列行里数（见模块头「第三种死法」）。
_MAX_ATTEMPTS = 3

# Spec-0065/T2: 「queued 行的锁却被人持着」判为泄漏的阈值（秒）。见 `_sweep_stalled`。
# 存活证明由 agent 子进程继承（`proc.hold_fd`），而它若泄漏了长命的孙子进程（MCP server / 后台 dev server），
# 那个孙子会一直持着这把锁 —— 于是该 subject 的行永远领不走。queued 行的锁**本就该是自由的**（持有者只可能是
# claimed 行的 worker），故「queued 且锁被占」超过这个阈值即判泄漏。给足余量：只覆盖释锁/回队之间的亚毫秒窗口。
_STALE_LOCK_SECONDS = 300

# Spec-0065/T2: worker 空队列时的轮询粒度（秒）——领不到活就 stop_event.wait(它) 再试，兼作停机响应上限。
_WORKER_POLL_SECONDS = 1.0

# Spec-0065/T2: SQLite 忙等超时（毫秒）——BEGIN IMMEDIATE 抢写锁抢不到时的自旋上限（序列化并发领取）。
# 生产者 + K 个 worker 同抢一把写锁，且 worker 持锁期间要发 GitHub 请求，故给得比「本地写一行」宽得多：
# 到点即抛 `database is locked`，而收尾里抛 = 行留 claimed（虽有 `_finish` 兜底，但那条路要多绕一圈回收）。
_BUSY_TIMEOUT_MS = 30000

# Spec-0065/T2: 单次认领内 `_reconcile` 的推进轮数上限。停止条件本该全是纯函数判断（QUIET/TERMINAL/fp 未变），
# 这道计数只兜**振荡**：fp 每轮都在变、却在两个状态间来回跳（review 打回 → implement 推新 head → review 又
# 打回 → …）。`fp == last_fp` 只记得**上一轮**，识别不了周期 ≥2 的环，于是它会一轮一次 LLM 地无限转下去，
# 直到 2 小时后 IN_FLIGHT 告警才有人管。到顶 → park 交人（振荡本就是「机器判不了、该人来定」）。
_MAX_RECONCILE_ROUNDS = 8

# Spec-0065/T2: `once=True` 排空的硬上限（秒）。排空是尽力而为的同步点、不是正确性来源（真相在 GitHub），
# 故它可以放弃；但它**不能永不返回**——`oa vigil --once` 挂死是最糟的结局。
_DRAIN_MAX_SECONDS = 3600

# Spec-0065/T2: attempt 戳的签名前缀——agent 零进展收工时盖在 PR 下的签名评论（护栏一，见模块头）。
# 全文形如 `<!-- openagents:attempt fp=9f2a1c… -->`，正文是 agent 自己的结论（给人看的工作日志）。
_ATTEMPT_MARKER = "<!-- openagents:attempt"

# Spec-0065/T2: e2e 证据评论的**溯源戳**——`<!-- openagents:e2e head=<40 位 sha> -->`。戳里的 head 必须
# 等于当前 head_sha 才算「这份证据是给这版代码跑的」；head 一前移，证据自动作废 → 分支⑨重跑（承
# Spec-0055 证据溯源戳；`gates.evidence_stamp_ok` 判的是同一件事，这里落成 GitHub 上的可见评论）。
_E2E_MARKER = "<!-- openagents:e2e head="

# ------------------------------ label：**我们做的决定**（客观事实读 GitHub 原生） ------------------------------
# 分界线（Spec-0065 §存储职责）：**决定打 label，事实读原生。**
#   - 「人来接手」「准入」「review 裁决」都是**我们做的决定**——GitHub 没有别的地方表达它们，故落 label。
#   - 「CI 绿不绿」「有没有冲突」是 **GitHub 自己维护的事实**——本就绑在 sha 上、一次读到；再复制一份成
#     label 就是造第二份真相，然后要负责让两份不打架（CI 重跑了谁去改 label？）。故**不打**。
#
# `needs-human` = agent 的**一等出口**（不是脚注）：任一分支里 agent 判断「我没辙 / 这要人来定」→ 打它 +
# 留一条说明理由的评论 → `_classify` 判 TERMINAL → **轮询立刻停止**，不再叫任何 agent。人摘掉 label，
# 谓词自动重新活过来（level-triggered 白送的自愈）。看门狗与 attempt 戳都只是**兜底**（防 agent 忘了打、
# 判错了、或压根没意识到自己在空转），正常路径根本走不到它们。
_LABEL_NEEDS_HUMAN = github.BLOCKED_LABEL  # "needs-human"，与全仓同源（github 是标签单一来源）
_LABEL_READY = "ready"  # 准入令牌（三态门控审过）
# Spec-0065/T2: `triage: human` 的准入提问评论的标记——「我问过了吗」的唯一真相（读 GitHub 现态，零本地
# 记忆）。不能靠「有没有我方签名评论」来判：attempt 戳、park 理由也都是我方评论，会把「问过」误判成 True。
_ADMIT_ASK_MARK = "<!-- openagents:admit-ask -->"
# Spec-0065/T2: 准入裁决的落地戳——「人这句话我已经判过了」的唯一真相。裁决先盖戳、再打 label：label
# 那步若挂了（`gh` 429/403），下一 tick 读回这条戳直接重试打 label，**不必再叫一次 agent**；否则 `gh`
# 每失败一轮就重判一轮，一条人类回复能烧掉 N 次 LLM。approved/refused 写进标记本身（读一条评论即可判）。
#
# 戳**挂在人那条评论的 comment id 上**，不挂时间戳。曾经拿 `stamp.created_at >= reply.created_at` 当判据，
# 有一个洞：GitHub 的 createdAt 只到**秒**，人的新回话与我们的裁决戳落在同一秒时 `>=` 恒成立 → 旧的
# refused 戳把新话彻底盖住 → **人再也无法点头**（fail-closed 从「谨慎」退化成「永久拒绝」）。改成 `>`
# 也不对（同秒的自己判自己 → 每 tick 重判）。id 是身份、不是刻度，比时间戳精确：换一句话就换一个 id。
_ADMIT_VERDICT_MARK = "<!-- openagents:admit-verdict:"
_ADMIT_APPROVED = "approved"
_ADMIT_REFUSED = "refused"
# Spec-0065/T2: 「人这句话已经烧过一次 agent」的戳——**在叫 agent 之前**盖，是 LLM 花费的准入券。
# 没有它，`stages.admit` 抛出（agent 输出不是 JSON / `_ActTimeout` / 429）就什么持久痕迹都不留：issue 既
# 没 `ready` 也没 `needs-human` → 下一 tick `_intake` 又扫到它 → **每 tick 烧一次 LLM，永远**。盖了它，
# 一条人类回复至多烧一次 agent：下一 tick 看到「有 try 戳、无裁决戳」即知上一轮判崩了 → 零 LLM 转人工。
_ADMIT_TRY_MARK = "<!-- openagents:admit-try:"
# Spec-0065/T2: 谁说的话算「人拍板」——GitHub 原生 authorAssociation。人闸若不认人，就不是人闸：任何路人
# 在公开仓库回一句「可以，做吧」都能把活派出去（准入闸对外部输入敞开，admitter 的提示词拦不住——它连
# 「该听谁的」都不知道）。fail-closed：关系读不到 / 是 CONTRIBUTOR / NONE ⇒ 这句话不算拍板，只当噪声。
_MAINTAINER_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})

# review 裁决落 label，但**必须把 head sha 带进 label 名**——裁决是「绑在某个 commit 上的判断」，不是
# 一个恒真的属性。若打成光秃秃的 `review-approved`：审的时候 head=abc123，审完 agent 又 push 了 def456 去
# 修 CI，label 还挂着 → `_classify` 一看「全绿 + 审过了」→ **合并一份没人审过的代码**。而合并不可逆。
# 带上 sha 后，head 一动 label 就对不上当前 head → 裁决自动作废 → 落回分支⑩重审。这是 GitHub 原生 PR
# review（天生绑 commit_id）白送的性质，我们用 label 复刻它，顺带让人在 UI 上一眼看见。
_LABEL_REVIEW_APPROVED_PREFIX = "review-approved:"  # review-approved:<sha7>
_LABEL_REVIEW_CHANGES_PREFIX = "review-changes-requested:"  # review-changes-requested:<sha7>
_SHA_LABEL_LEN = 7  # label 里嵌的 head_sha 短格式长度（与 git 短 sha 一致）

_REVIEW_APPROVED = "APPROVED"
_REVIEW_CHANGES_REQUESTED = "CHANGES_REQUESTED"

# ------------------------------ 四值判定的取值（见 `_Verdict`） ------------------------------
# 队列里有该 subject 的 claimed 行 = 我的 agent 正在跑它。**必须是第一道判定**，否则看门狗会把一个正在
# 写代码的 agent（跑 8 分钟很正常）当成「状态 5 分钟没动」而误挂 needs-human。
_IN_FLIGHT = "in-flight"
# merged / closed / needs-human。轮询停止。人摘掉 needs-human，谓词自动重新活过来（level-triggered 白送）。
_TERMINAL = "terminal"
# 现在没我的活，等状态自己变。不入队；交 `_watchdog` 按 reason 的阈值判 age。
_QUIET = "quiet"
# 现在该动手。`INSERT OR IGNORE` 入队。
_ACTIONABLE = "actionable"

# ------------------------------ QUIET 的四个成因（`_Verdict.reason`） ------------------------------
# 它们的自然时长差两个数量级，故阈值必须按 reason 分档、且可配（`_WATCHDOG_DEFAULTS`）。
_AWAITING_BLOCKERS = "awaiting-blockers"  # 等上游 subject 被合并
_AWAITING_MERGEABILITY = "awaiting-mergeability"  # GitHub 后台异步算 merge ref
_AWAITING_CI = "awaiting-ci"  # CI runner（pending，**或当前 head 上零个 check**）
_AWAITING_EFFECT = "awaiting-effect"  # agent 刚那一下异步落地（**或它根本没做**）

# ------------------------------ ACTIONABLE 的动作（`_Verdict.action`） ------------------------------
# 即 `_reconcile` 分支表的出口；`_act` 据此分派。
_ACT_REPLY = "reply"  # 最新评论是人发的 → 回话
_ACT_SOLVE = "solve"  # 还没有 PR → 竖切开 PR
_ACT_REBASE = "rebase"  # 冲突 → 变基（**必须排在 CI 前**，见 `_classify`）
_ACT_FIX_CI = "fix-ci"  # 当前 head 上 CI 红 → 修
_ACT_E2E = "e2e"  # e2e 证据缺失 / head_sha 陈旧 → 补
_ACT_REVIEW_OR_FIX = "review-or-fix"  # review 缺失 / 陈旧 / CHANGES_REQUESTED
_ACT_READY = (
    "ready"  # 全绿 + APPROVED 但仍 draft → 转正（Spec-0017：**必须排在 merge 前**，见 `_classify`）
)
_ACT_MERGE = "merge"  # 全绿 + APPROVED + 非 draft → 合

# Spec-0066/T2: TERMINAL 的阶段细分（`_phase_of` 据 facts 把单一 TERMINAL 拆成三态，供墙钟计时区分收口原因）。
# QUIET 的 phase 直接取 `verdict.reason`（_AWAITING_*），ACTIONABLE 直接取 `verdict.action`（_ACT_*），
# IN_FLIGHT 取 `_IN_FLIGHT`——故只有 TERMINAL 需要额外三个字面量。
_PHASE_MERGED = "merged"  # 已合并收口
_PHASE_CLOSED = "closed"  # 被关闭收口
_PHASE_NEEDS_HUMAN = _LABEL_NEEDS_HUMAN  # needs-human 收口（"needs-human"，与全仓同源）

# ------------------------------ facts 的枚举取值（GitHub 事实的归一化投影） ------------------------------
_MERGE_CLEAN = "clean"
_MERGE_DIRTY = "dirty"  # CONFLICTING / DIRTY / BEHIND（都得先动分支，才谈得上读 CI）
_MERGE_UNKNOWN = "unknown"  # GitHub 还没算完——**不等于「没冲突」**（见 `_sense`）

_CI_SUCCESS = "success"
_CI_FAILURE = "failure"
_CI_PENDING = "pending"
_CI_NONE = "none"  # 当前 head 上**一个 check 都没有**——是「还在等」，不是「绿了」

_KIND_ISSUE = "issue"
_KIND_PR = "pr"

_AGENT = agent_config.OWNER_AGENT
_HUMAN = agent_config.OWNER_HUMAN
_SKIP = agent_config.OWNER_SKIP

# Spec-0065/T2: 默认优先级——**先收尾在制品，再开新工**。一个近乎合完的 PR 正占着一条依赖链的下游；
# 开一个新 issue 只是增加在制品。`reply` 最高因为**人在等**。可被 `run_vigil(priority_fn=…)` 整体替换。
_PRIORITY_DEFAULTS = {
    _ACT_REPLY: 6,
    _ACT_MERGE: 5,
    _ACT_READY: 5,  # Spec-0017: 转正是「离 merge 一步」的机械动作，与 merge 同高优先（先收尾在制品）。
    _ACT_REVIEW_OR_FIX: 4,
    _ACT_E2E: 3,
    _ACT_FIX_CI: 2,
    _ACT_REBASE: 2,
    _ACT_SOLVE: 1,
}

# Spec-0065/T2: 看门狗阈值（秒），按 QUIET 成因分档，可被 `run_vigil(watchdog_thresholds=…)` 覆盖。
# **宁可给宽**：设窄了会把正常在跑的 CI 误 park，比不看门更糟；而 park 只是「打个 label + 贴条诊断」、
# 完全可逆（人摘掉 label 系统立刻复活），所以晚叫人的代价远小于误杀。
# `_AWAITING_BLOCKERS` 默认 None（关）：上游 blocker 有自己的看门狗，在下游重复计时只会误杀。
_WATCHDOG_DEFAULTS: dict[str, int | None] = {
    _AWAITING_BLOCKERS: None,
    _AWAITING_MERGEABILITY: 180,
    _AWAITING_CI: 3600,
    _AWAITING_EFFECT: 300,
}

# Spec-0065/T2: 队列表 DDL。**一行 = 一个 subject**（不是「一行一事件」）。
#
# 没有 `kind` 列：事件类型（solve/advance/reply）是**GitHub 现态的一份拷贝**，而现态每 tick 都要重读——
# 按存储职责原则（无重叠、无对账），它不该存在。而且它买不到任何并行：三类事件对同一 subject 本来就必须
# 串行，所以「一行一事件」还得额外用 `NOT EXISTS` 子查询把并行**再收回来**——它制造了一个只有它自己才需要
# 解决的问题。砍掉后 `dedup_key` / `NOT EXISTS` / 同-issue 索引 / 三路分派**一起消失**。
#
# **没有 lease 列**——回收判据是 flock（进程死了内核放锁），不是超时猜死。`worker_pid` / `claimed_at` 都
# **不作存活裁决**：前者仅供人 `ps` 诊断，后者只喂 IN_FLIGHT 告警。
#
# `subject` 是 TEXT 不是 INTEGER：`issue INTEGER NOT NULL` 表达不了**无 issue 归属的裸 PR**
# （旧串行 vigil 明确支持 `run.issue_number is None` 的「open PR 迭代源」）。
_SCHEMA = """
CREATE TABLE IF NOT EXISTS work_queue (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    subject          TEXT    NOT NULL UNIQUE,        -- "issue:5" | "pr:12"
                                                     -- 去重 + 同-subject 互斥 + 幂等入队，三合一
    priority         INTEGER NOT NULL DEFAULT 0,     -- 越大越先（领取时定序，不冻结在入队时刻）
    enqueued_at      TEXT    NOT NULL,               -- ISO；等优先级下的 FIFO tie-break
    status           TEXT    NOT NULL DEFAULT 'queued',   -- queued | claimed
    worker           TEXT,                           -- claimed 者标识（可观测）
    worker_pid       INTEGER,                        -- 持有者进程号——仅供人 ps 诊断，不作存活裁决
    claimed_at       TEXT,                           -- 领取时刻；只喂 IN_FLIGHT 告警，不作回收判据
    attempts         INTEGER NOT NULL DEFAULT 0      -- 领取后未收工的次数；超 _MAX_ATTEMPTS → park
);
CREATE INDEX IF NOT EXISTS ix_work_queue_claimable
    ON work_queue (status, priority DESC, enqueued_at ASC);
"""


@dataclass(frozen=True)
class _Facts:
    """`_classify` 读的、且 `_fingerprint` 哈希的**全部**字段——两者的输入集在此合一，故不可能漂移。

    **不变式：本 dataclass 的字段集 ≡ 分支表读的字段集 ≡ fp 的哈希输入集。** 违反的两种后果都是静默的：
    - **少一个字段 → 静默瞎掉一整类活。** 最经典的是漏 `mergeable_state`：别人往 main 合了个 PR、base
      前移、你的 PR 变冲突——没有新评论、没有新 commit、CI 结果没变 → 谓词察觉不到 → PR 烂在那里。
    - **混进时间戳 → 护栏一失效。** 见 `_Clock`。

    `deps_done` 必须在这里，这条最容易漏：issue A `blocked_by` B，B 的 PR 合了——**A 自己的 PR / CI /
    评论一个字节都没变**。若 fp 里没有 `deps_done`，A 的 fp 不变、A 永远不会被重新考虑，**整个依赖图卡死
    在第一个节点**，而 issue graph 并行正是本 spec 的核心卖点。

    **反过来，「最新评论的 ID」绝不能在这里**（只留 `latest_comment_is_ours` 这个布尔）。它是护栏一的自毁
    开关：worker 零进展收工时会**盖一条 attempt 戳评论**——若 comment id 进了 fp，盖戳这个动作本身就把 fp
    改了 → 生产者下一 tick 算出的 fp 与戳里记的对不上 → 判「全新情况」→ 重新入队 → 又叫 agent → 又撞墙 →
    又盖一条新戳（又是新 fp）→ **无限重叫 LLM，正是护栏一要防的那件事**。而丢掉 id 一个信号都不丢：分支②
    只需要「最新一条是不是人发的」，人再留言时 `is_ours` 会从 True 翻回 False，fp 照样变。
    """

    subject: str  # "issue:5" | "pr:12"
    pr_number: int | None  # issue 尚无 PR → None → 分支④ solve
    head_sha: str | None
    merged: bool  # 分支①
    closed: bool  # 分支①
    labels: frozenset[str]  # needs-human → 分支①（TERMINAL）；ready → 准入；review-* → 分支⑩⑪
    deps_done: bool  # blocked_by 的对端是否全部关闭 → 分支③
    mergeable_state: str | None  # clean | dirty | unknown | None → 分支⑤⑥（GitHub 事实，读原生）
    ci: str  # success | failure | pending | none —— **当前 head_sha 上的**（GitHub 事实，读原生）
    e2e_head_sha: str | None  # e2e 证据评论上的溯源戳；≠ head_sha 即陈旧 → 分支⑨
    review_state: str | None  # APPROVED | CHANGES_REQUESTED | None → 分支⑩⑪
    review_commit_id: (
        str | None
    )  # 裁决绑定的 commit 短 sha（从 review-*:<sha7> label 解析）；≠ head sha7 即陈旧
    latest_comment_is_ours: (
        bool  # 最新评论是不是我方签名 → 否则「人有新话」→ 分支②。**不存 comment id**
    )
    is_draft: bool = (
        False  # Spec-0017/T2: PR 是否 draft（末位默认 False）→ 分支⑪ 自愈转正（排在 merge 前）。
    )
    # 转正动作把它从 True→False，改 fp、记为**真进展**（与 push 改 head_sha 同类），故护栏一不误触；
    # 转正没成功则 is_draft 不变、fp 不变、attempt 戳照常兜底。是每 tick 复检的一等事实（level-triggered）。


@dataclass(frozen=True)
class _Clock:
    """只有 `_watchdog` 读的时间面。**绝不进 `_fingerprint`。**

    若混进 fp：一个 check run 开始跑就会刷新 `started_at` → fp 变 → attempt 戳失配 → agent 被重新叫起，
    尽管分支表根本不看这个字段。护栏一当场失效。

    `last_progress_at` 让「卡了多久」成为**当前态的纯函数**——每个 GitHub 对象都自带时间戳，不需要任何本地
    记忆（重启 / 丢库 / 换机器都不影响）。head 一变，它自动刷新、计时归零。
    """

    last_progress_at: datetime | None  # max(head 推送时间, 最新 check.started_at,
    #                                        最新评论时间, 最新 attempt 戳时间)


@dataclass(frozen=True)
class _Observed:
    """`_sense` 的产物：一个 subject 在某一时刻的 GitHub 现态快照（不可变、不落盘、非第二份真相）。

    拆 `facts` / `clock` 两半是硬约束——见各自 docstring。拆开之后「fp 字段集 ≡ 分支表输入集」才是一条能
    写成测试的不变式（`tests/test_recipe_vigil.py` 直接对 `dataclasses.fields(_Facts)` 断言）。
    """

    facts: _Facts
    clock: _Clock


@dataclass(frozen=True)
class _Verdict:
    """`_classify` 的四值判定。`reason` 只在 QUIET 时有值，`action` 只在 ACTIONABLE 时有值。"""

    kind: str  # _IN_FLIGHT | _TERMINAL | _QUIET | _ACTIONABLE
    reason: str | None = None  # QUIET 的成因：_AWAITING_*（决定看门狗用哪档阈值）
    action: str | None = None  # ACTIONABLE 的动作：_ACT_*（决定 `_act` 的分派与 priority）


class _ActTimeout(RuntimeError):
    """Spec-0065/T2: 单次 `_act` 超 `_AGENT_TIMEOUT_SECONDS`——子进程已被杀，行交 `_requeue_or_park`。"""


def run_vigil(
    *,
    backend: Any,
    state: RuntimeState,
    work_dir: Path,
    config: agent_config.AgentConfig,
    once: bool,
    concurrency: int = 1,
    agent_id: str = "",
    priority_fn: Callable[..., Any] | None = None,
    watchdog_thresholds: dict[str, int | None] | None = None,
    now_fn: Callable[[], datetime] | None = None,
) -> None:
    """Run the graph-driven vigil main loop until interrupted.

    Spec-0065/T2: 图驱动并行守夜主循环——K 个常驻 worker 领 work_queue，生产者每 tick level-triggered 补给

    建表（`_init_db`）后起 `concurrency`(=K) 个 worker 线程跑 `_worker_loop`（消费者：`_claim_next` 原子领
    一个 subject + 取 flock 存活证明 → `_reconcile` **推进到卡住为止** → `_mark_done` 先删行后释锁 → 再领）；
    主线程跑**生产者 tick 循环** `_producer_tick`：`_reclaim_dead`（凭 flock 判死）→ `_intake`（三态准入打
    `ready` + curator 排 `blocked_by` 边）→ 对每个 subject `_sense`→`_classify`→（ACTIONABLE 且无同 fp 的
    attempt 戳 → `_enqueue`；QUIET → 交 `_watchdog`；IN_FLIGHT → 超龄只告警；TERMINAL → 略过）。

    **数据流严格单向**：生产者只写 GitHub + 写队列（`_enqueue`），**从不领活**；worker 只读队列
    （`_claim_next`）+ 写 GitHub + 删队列行，**从不生产**。两者对 `work_queue` 的并发写全部经
    `BEGIN IMMEDIATE` 序列化——**无需任何进程内锁**（只留一个 `stop_event` 做收池信号）。

    **没有批屏障**：worker 跑完立即领队首。对照「批」模型（每轮 sense → 跑整批 → sleep）：K=4 选中 4 个
    subject，3 个两分钟跑完、1 个跑四十分钟，那 3 个 freed slot 就空转 38 分钟。拆掉屏障后 slot 复用延迟从
    「同批最慢」降到「≤ 一次 pull」（`_WORKER_POLL_SECONDS`）。

    `concurrency` 是并发上限；**默认 K=1 即退化串行**。每 tick 从 GitHub 重推进度，任意一 tick 崩掉只记日志
    跳过（`once=False`），下一 tick 自愈——守夜第一要务是「活着进下一轮」。`config` 是单一真源（stages 三态
    + agents 后端映射 + base/labels/interval）。DB 在 `work_dir/.openagents/vigil-queue.db`。

    生命周期：
    - `once=True`（测试/单趟）：跑**一个** `_producer_tick`，再 `_drain_queue` 轮询到表内无 queued 且无
      claimed 行 → 收池返回（给测试确定性同步语义）。被本轮解锁、但本轮未再感知的下一层留给下一次调用。
    - `once=False`（守护）：tick→sleep(interval) 循环。`_producer_tick` 抛异常记日志继续（**不杀生产者**）；
      单 subject 异常在 `_worker_loop` 内隔离（**不杀 worker**）。
    - `KeyboardInterrupt`：`stop_event` 置位 → worker 领完当前活自然退出（自己删行 + 释锁）；queued 行留
      DB——**幂等 + 持久**，安全放弃、重启续跑。
    - `kill -9` / OOM / 断电：`claimed` 行留在库里，但锁随进程被内核回收 → 重启后第一个 `_reclaim_dead` 就
      抢得到锁 → 判死 → 行立刻回 `queued`。**恢复延迟 = 一个 tick，不是一个租约。**

    Args:
        backend: 派 agent 的后端（`engine.run_agent` 透传）；worker 领到 subject 用它跑 reconcile 分支。
        state: `RuntimeState` 运行态存储，记录每个 subject 的进度与指纹分流依据。
        work_dir: 仓库工作目录；队列 DB 落在 `work_dir/.openagents/vigil-queue.db`。
        config: 单一真源配置——stages 三态 + agents 后端映射 + base/labels/interval。
        once: True 只跑一个 `_producer_tick` 再 `_drain_queue` 排空即返回（cron/CI/测试）；False 长驻循环。
        concurrency: 常驻 worker 线程数 K（并发上限）；默认 1 即退化串行。
        agent_id: 本守夜人签名标识，用于认领标签与签名回帖；缺省空串。
        priority_fn: 排 subject 优先级的偏函数；None 用内置 `_priority_default`。
        watchdog_thresholds: QUIET 看门狗各阈值覆盖；None/缺键回落 `_WATCHDOG_DEFAULTS`。
        now_fn: 取当前时间的注入点（测试可定桩）；None 用 `datetime.now(UTC)`。

    Raises:
        Exception: once=True 时单个 `_producer_tick` 的异常上抛让调度器看见非零退出；once=False 时吞掉
            记日志继续（守夜第一要务是「活着进下一轮」）。KeyboardInterrupt 两种模式都吞掉、收池返回。
    """
    resolved_priority = priority_fn or _priority_default
    resolved_now = now_fn or (lambda: datetime.now(UTC))
    thresholds = dict(_WATCHDOG_DEFAULTS) | (watchdog_thresholds or {})
    db_path = Path(work_dir) / ".openagents" / _QUEUE_DB_FILENAME
    _init_db(db_path=db_path)
    stop_event = threading.Event()

    workers = [
        threading.Thread(
            target=_worker_loop,
            kwargs={
                "db_path": db_path,
                "backend": backend,
                "state": state,
                "work_dir": Path(work_dir),
                "config": config,
                "agent_id": agent_id,
                "now_fn": resolved_now,
                "stop_event": stop_event,
                "worker_id": f"vigil-worker-{index}",
            },
            name=f"vigil-worker-{index}",
            daemon=True,
        )
        for index in range(max(1, concurrency))
    ]
    for worker in workers:
        worker.start()

    # Spec-0065/T2: 「哪些 subject 的锁上一 tick 就被人持着」的跨 tick 记忆（`_sweep_stalled` 的闸 2）。
    # 归生产者独有（单线程），故不需要锁；重启即清空，最坏是泄漏的行多等一个 `_STALE_LOCK_SECONDS` 才交人。
    seen_locked: dict[str, datetime] = {}
    try:
        while True:
            try:
                _producer_tick(
                    backend=backend,
                    state=state,
                    work_dir=Path(work_dir),
                    config=config,
                    agent_id=agent_id,
                    db_path=db_path,
                    priority_fn=resolved_priority,
                    thresholds=thresholds,
                    seen_locked=seen_locked,
                    now=resolved_now(),
                )
            except KeyboardInterrupt:
                raise
            except Exception as exc:  # noqa: BLE001 —— 守夜第一要务是「活着进下一轮」
                if once:
                    raise
                _log(message=f"✗ 本轮生产者 tick 失败，跳过、{config.interval}s 后再扫一轮：{exc}")
            if once:
                _drain_queue(  # 轮询排空 → 测试确定性同步语义
                    db_path=db_path,
                    work_dir=Path(work_dir),
                    seen_locked=seen_locked,
                    now_fn=resolved_now,
                    stop_event=stop_event,
                    agent_id=agent_id,
                )
                return
            _log(message=f"… 守夜中，{config.interval}s 后再扫一轮（Ctrl-C 停止）")
            time.sleep(config.interval)
    except KeyboardInterrupt:
        _log(message="✓ 守夜人已停止（Ctrl-C）")
    finally:
        stop_event.set()
        for worker in workers:
            worker.join(timeout=_WORKER_POLL_SECONDS * 2)


def run_fleet(*, config: agent_config.AgentConfig, once: bool) -> None:
    """多仓库并发守夜：`config.repos` 每仓一子进程跑 `run_vigil`，复用 `utils.fleet` 进程监管器。

    为什么进程而非线程：**gh/git 绑进程 cwd**，一仓一进程才拿到 cwd 隔离 + 崩溃隔离 + 真并行（承旧 fleet
    论证；#77 已踩过「线程共享 cwd → 多仓交叉写」）。注意这与 `run_vigil` 内部的 K 线程**不冲突**：那是
    **同一个仓**内按 subject 并发（共享 cwd 正确），这里是**跨仓**并发（必须换 cwd）。

    单仓（`repos` 只一项）时父进程直接顺跑，不起子进程（理念 1 奥卡姆）。
    """
    from openagents.utils import fleet as fleet_util

    if len(config.repos) == 1:
        repo = config.repos[0]
        _run_repo_inline(repo=repo, agents=config.agents, release=config.release, once=once)
        return
    fleet_util.Fleet(spawn=_default_spawn, queue_factory=fleet_util.default_queue).run(
        plans=config.repos, once=once
    )


# --------------------------------------------------------------------------------------------------
# 感知（三个纯函数 + 看门狗）：sense 是唯一的 GitHub 读；classify / fingerprint 吃同一个 _Facts。
# --------------------------------------------------------------------------------------------------


def _sense(*, config: agent_config.AgentConfig, subject: str) -> _Observed:
    """**唯一的 GitHub 读**：把一个 subject 的现态收拢成一个不可变 `_Observed`（level-triggered reconcile）。

    这些读取在旧串行 vigil 里已全部存在，只是散在 `_route_triage` / `advance_merge` / `_reply_one_pr`
    里各读各的。`_sense` 不是新功能，是把它们**归位到一处**——「fp 字段集 ≡ 分支表输入集」这条不变式才有
    地方挂。

    **两个必须写死在这里的坑**（否则分支表会在正确的顺序上读到错误的值）：
    1. `ci` 必须是「**当前 `head_sha` 上的** CI」，不是「这个 PR 最近一次 CI」——`gh pr checks` 天然按 head
       报，故 `github.check_snapshot` 一次读到；且**零个 check 记 `none` 而不是 `success`**，否则一个
       workflow 从未启动的 PR 会被读成「CI 绿了」→ 直接合并一份没跑过 CI 的代码。
    2. `mergeable_state` 的 `unknown` / `None` 是「GitHub 还没算完」，**不等于「没冲突」**。它必须落到
       `_AWAITING_MERGEABILITY`，绝不能穿透到 CI 分支——**冲突的 PR 拿不到 merge ref，GitHub 压根不给它
       任何 check**（本仓已踩过）。故本函数**只在 mergeable=clean 时才去读 check**：不先挡住的话，症状是
       「CI 卡住了」，病因是「有冲突」。

    **三态 `skip` 在此归一**（`OWNER_SKIP` = 不设此闸、当 PASS 放行）：`ci: skip` → `ci=success`；
    `e2e: skip` → 证据戳记当前 head；`review: skip` → 裁决记 `APPROVED@head`。这让 `_classify` 保持纯粹的
    机械分支表、不吃 config——策略只在 `_sense`（skip）与 `_act`（agent/human）两处出现。

    依赖读走 GitHub 原生 issue dependencies（2025-08 GA）：`GET /repos/{o}/{r}/issues/{n}/dependencies/
    blocked_by` 的响应**自带各 blocker 的 `state`**，故一次调用同时拿到「边」和「blocker 关没关」→
    `deps_done` 直接算出，无需第二轮查询。(https://docs.github.com/en/rest/issues/issue-dependencies)

    规模注意：每 subject 一次 `_sense` ≈ 数次 REST 往返，而认证配额是 5000 请求/小时——上百 subject 时需
    批量化（GraphQL 一条 query 拉多 subject，见 spec Future）。
    """
    kind, number = _split_subject(subject=subject)
    labels: set[str] = set()
    deps_done = True
    pr_number: int | None = None
    progress: list[str] = []

    if kind == _KIND_ISSUE:
        issue = github.get_issue(number=number)
        labels |= set(issue.labels)
        blockers = github.list_blocked_by(number=number)
        deps_done = all(blocker.state == "CLOSED" for blocker in blockers)
        # 坑 3：查 PR 必须**不限状态**（`pr_for_branch`，非 open-only 的 `find_pr_by_branch`）——PR 一合并
        # 就从 open 列表消失，用 open-only 的查法会在合并后的下一圈把这个 issue 读成「还没有 PR」→ 分支④
        # 再开一个 PR 把同一个 issue 重做一遍。`merged` 是终止条件，必须能从「那个 PR 现在什么状态」读出来。
        pr = github.pr_for_branch(branch=f"{_BRANCH_PREFIX}{number}")
        pr_number = pr.number if pr is not None else None
    else:
        pr_number = number

    merged = False
    closed = False
    head_sha: str | None = None
    mergeable_state: str | None = None
    ci = _CI_NONE
    e2e_head_sha: str | None = None
    latest_comment_is_ours = True
    is_draft = False  # Spec-0017/T2: 无 PR 时恒非 draft（分支④ solve，不触转正支）。

    if pr_number is not None:
        snapshot = github.pr_snapshot(pr_number=pr_number)
        labels |= set(snapshot.labels)
        merged = snapshot.state == "MERGED"
        closed = snapshot.state == "CLOSED"
        head_sha = snapshot.head_sha or None
        is_draft = (
            snapshot.is_draft
        )  # 与 state/head/mergeable 同源一次 pr_snapshot 往返读入（免多一次网络）。
        mergeable_state = _mergeable_state(snapshot=snapshot)
        progress.append(snapshot.head_pushed_at)
        if mergeable_state == _MERGE_CLEAN:  # 坑 2：UNKNOWN / dirty 时**不读 CI**
            checks = github.check_snapshot(pr_number=pr_number)
            ci = _ci_state(snapshot=checks)
            progress.append(checks.latest_started_at)
        comments = github.list_comments(pr_number=pr_number)
        e2e_head_sha = _latest_e2e_sha(comments=comments)
        latest_comment_is_ours = _latest_is_ours(comments=comments)
        progress.extend(comment.created_at for comment in comments)
    elif kind == _KIND_ISSUE:
        # Spec-0065/T2: issue 尚无 PR 时，进度时钟也必须从 **issue 自己的评论流** 走。少了这一步，
        # `progress` 恒空 → `last_progress_at` 恒 None → 护栏二（QUIET 看门狗）对整个 `solve` 阶段**永久
        # 失效**：一个空转的 solve（agent 跑完没推 PR → fp 没变 → `_reconcile` 盖同-fp attempt 戳 → 生产者
        # 降级 QUIET(awaiting-effect)）会**永远**卡在那里——`_watchdog` 因 `last_progress_at is None` 直接
        # 返回 False，needs-human 永不触发。这正是 §5 表承诺「状态该动却不动 → 看门狗兜底」不可能发生的
        # 静默永久卡死。attempt 戳与人类评论都落在 issue 上，读它们喂进度时钟（成因时钟一致：head 一推、
        # 有 PR 后自然改走 PR 分支）。
        issue_comments = github.list_issue_comments(number=number)
        progress.extend(comment.created_at for comment in issue_comments)
        # Spec-0016/T4: 已准入（ready）、尚无 PR 的 issue，其页面评论流也接进 reply 分支②（issue #149：
        # 把「新人类评论→agent 签名回复」从 PR 扩到 issue 页）。**只在 ready 时激活**：无 ready 的 issue
        # 仍归**准入面** admitter（`_ask_human` 处理 triage:human 入闸对话），准入后才归本回复面——`ready`
        # 是这条边界的单一判据（见 §14）。复用既有纯函数 `_latest_is_ours`（最新一条非我方签名 → 有人有
        # 新话 → 分支②派 replier）；**不新增携 comment id 的字段**，fp 全集不变（护栏一不自毁，见 `_Facts`）。
        if _LABEL_READY in labels:
            latest_comment_is_ours = _latest_is_ours(comments=issue_comments)

    review_state, review_commit_id = _review_from_labels(labels=labels)

    owners = config.stages
    if owners.owner_of(stage=agent_config.STAGE_CI) == _SKIP:
        ci = _CI_SUCCESS
    if owners.owner_of(stage=agent_config.STAGE_E2E) == _SKIP:
        e2e_head_sha = head_sha
    if owners.owner_of(stage=agent_config.STAGE_REVIEW) == _SKIP:
        review_state, review_commit_id = _REVIEW_APPROVED, _short(sha=head_sha)

    facts = _Facts(
        subject=subject,
        pr_number=pr_number,
        head_sha=head_sha,
        merged=merged,
        closed=closed,
        labels=frozenset(labels),
        deps_done=deps_done,
        mergeable_state=mergeable_state,
        ci=ci,
        e2e_head_sha=e2e_head_sha,
        review_state=review_state,
        review_commit_id=review_commit_id,
        latest_comment_is_ours=latest_comment_is_ours,
        is_draft=is_draft,
    )
    return _Observed(facts=facts, clock=_Clock(last_progress_at=_latest_ts(stamps=progress)))


def _classify(*, facts: _Facts, in_flight: bool) -> _Verdict:
    """纯函数：一个 `_Facts` → 四值判定。**这就是 reconcile 分支表本身**（`_reconcile` 与生产者共用它）。

    它是旧串行 vigil 的 `advance_merge`（终态 → 冲突 → CI → e2e → review → merge，每支各自 early-return）在
    头上接了两支——「无 PR → solve」和「最新评论是人发的 → reply」。三趟全量扫看着是三件事，其实是同一个
    问题（「这个 subject 现在该做什么」）的三个切面。

        ① merged / closed / **needs-human** ........... TERMINAL      ← agent 的一等出口，见下
        ② 最新评论是人发的（无我方签名）............... ACTIONABLE: reply
        ③ 依赖未全关闭 ................................ QUIET(awaiting-blockers)
        ④ 还没有 PR ................................... ACTIONABLE: solve
        ⑤ mergeable_state = UNKNOWN / null ............ QUIET(awaiting-mergeability)
        ⑥ 冲突（mergeable_state = dirty）.............. ACTIONABLE: rebase
        ⑦ 当前 head 上 CI = pending / 零个 check ...... QUIET(awaiting-ci)
        ⑧ 当前 head 上 CI = failure ................... ACTIONABLE: fix-ci
        ⑨ e2e 证据缺失 / head_sha 陈旧 ................ ACTIONABLE: e2e
        ⑩ 无 review-* label / 其 sha ≠ 当前 head /
          review-changes-requested ................... ACTIONABLE: review-or-fix
        ⑪ 全绿 + approved@head + **is_draft** ......... ACTIONABLE: ready   （自愈转正，排在 merge 前）
        ⑫ 全绿 + approved@head + **非 draft** ......... ACTIONABLE: merge

    **`needs-human` 是 agent 的一等出口，不是兜底。** 任一分支里 agent 判断「我没辙 / 这要人来定」——CI 是
    上游 flaky、需求本身有歧义、要动的东西超出授权——它就**自己打 `needs-human` + 留一条说明理由的评论**，
    ①当场判 TERMINAL、**轮询立刻停止**。这是最快、最准、最便宜的收口：不烧一次多余的 LLM 调用，不等任何
    超时，理由直接写在 issue 上给人看。人摘掉 label，谓词自动重新活过来。护栏二（看门狗超时）与护栏一
    （attempt 戳）都只是**兜底**——防 agent 忘了打、判错了、或压根没意识到自己在空转。

    **⑩⑪ 的 review 裁决从 `review-*:<sha7>` label 读，而 sha 必须参与匹配。** 裁决是「绑在某个 commit 上的
    判断」：审的时候 head=abc123，审完 agent 又 push 了 def456 修 CI——若 label 是光秃秃的 `review-approved`，
    这里会读成「审过了」→ ⑪ → **合并一份没人审过的代码**，而合并不可逆。带 sha 后 head 一动裁决自动作废、
    落回⑩重审（见 `_LABEL_REVIEW_APPROVED_PREFIX`）。

    **四处顺序是正确性依赖，不是风格**（改动前先读这里）：
    - **①在最前**——`needs-human` 一挂，任何分支都不许再动手（它是人接管的信号）。
    - **②在③之后一切之前**——人说「先别合，我有疑问」必须能抢在 merge 前面。**合并不可逆。**
    - **⑤⑥在⑦前**——conflict 在 CI 前是硬依赖：冲突的 PR 没有 merge ref → GitHub 不给它 check → ⑦会把
      「零个 check」读成「CI 还在跑」，然后 `awaiting-ci` 一直等到超时（见 `_sense` 坑 2）。
    - **⑦⑧只看当前 `head_sha`**——否则会派 agent 去修已经修好的代码（见 `_sense` 坑 1）。
    - **⑪在⑫前**（Spec-0017）——draft PR 合不了（GitHub 拒合 draft），`merge: human` 时人也被 draft 墙挡住
      （#168 根因）：转正必须先于任何（agent 或 human 的）合并动作，故 `is_draft` 支排在 merge 之前。

    `in_flight`（队列里有该 subject 的 claimed 行 = 我的 agent 正在跑它）**必须先于一切判定**——否则看门狗
    会把一个正在写代码的 agent（跑 8 分钟很正常）当成「状态 5 分钟没动」而误挂 needs-human。

    **`_reconcile` 调用本函数时必须传 `in_flight=False`**——worker 自己**就是**那个 in-flight 的持有者，若
    传 True，它领到活的第一件事就是判定「这活有人在干」→ 立刻收工 → **每个 worker 都空转，系统一动不动**。
    `in_flight` 是**生产者独有**的概念（「别人在干」），worker 视角里它恒为 False。

    护栏一（「有 fp 相同的 attempt 戳 → 降级为 QUIET(awaiting-effect)」）**不在这里**——它需要读 GitHub 上
    的戳，是有副作用的，由生产者在 `_classify` 之外包一层（见 `_producer_tick`）。本函数保持纯。
    """
    if in_flight:
        return _Verdict(kind=_IN_FLIGHT)
    if facts.merged or facts.closed or _LABEL_NEEDS_HUMAN in facts.labels:
        return _Verdict(kind=_TERMINAL)
    if not facts.latest_comment_is_ours:
        return _Verdict(kind=_ACTIONABLE, action=_ACT_REPLY)
    if not facts.deps_done:
        return _Verdict(kind=_QUIET, reason=_AWAITING_BLOCKERS)
    if facts.pr_number is None:
        return _Verdict(kind=_ACTIONABLE, action=_ACT_SOLVE)
    if facts.mergeable_state in (None, _MERGE_UNKNOWN):
        return _Verdict(kind=_QUIET, reason=_AWAITING_MERGEABILITY)
    if facts.mergeable_state == _MERGE_DIRTY:
        return _Verdict(kind=_ACTIONABLE, action=_ACT_REBASE)
    if facts.ci in (_CI_PENDING, _CI_NONE):
        return _Verdict(kind=_QUIET, reason=_AWAITING_CI)
    if facts.ci == _CI_FAILURE:
        return _Verdict(kind=_ACTIONABLE, action=_ACT_FIX_CI)
    if facts.e2e_head_sha != facts.head_sha:
        return _Verdict(kind=_ACTIONABLE, action=_ACT_E2E)
    if facts.review_state != _REVIEW_APPROVED or facts.review_commit_id != _short(
        sha=facts.head_sha
    ):
        return _Verdict(kind=_ACTIONABLE, action=_ACT_REVIEW_OR_FIX)
    # ⑪ 全绿 + approved@head 但仍 draft → 先转正（Spec-0017）。**必须排在 ⑫ merge 前**：draft PR 合不了
    # （GitHub 拒合 draft），且 `merge: human` 时人也被 draft 墙挡住（#168 根因）——转正必须先于任何合并动作。
    if facts.is_draft:
        return _Verdict(kind=_ACTIONABLE, action=_ACT_READY)
    return _Verdict(kind=_ACTIONABLE, action=_ACT_MERGE)


def _fingerprint(*, facts: _Facts) -> str:
    """纯函数：`_Facts` 的**全部**字段 → 一个稳定哈希。**这是护栏一的「我出手时看到的状态」。**

    `fp` 没变 ⟺ 分支表关心的每一个字段都没动 ⟺ **零进展**——任何真实推进都必然改 fp（push 改 `head_sha`、
    rerun 改 `ci`、提 review 改 `labels` 里的 `review-*:<sha7>`、上游合并改 `deps_done`）。所以「agent 出手后
    fp 没变」= 它撞墙了，再叫一次只是在同一堵墙上再撞一次。

    **但反向不成立：存在「改了 fp 却没推进」的动作**，而它们会让护栏一自毁。最险的一个是 attempt 戳自己——
    它是一条新评论。故 `_Facts` **不含 comment id**（见其 docstring），盖戳不改 fp。给 `_Facts` 加任何新字段
    前先问：**worker 收工时会不会顺手改到它？** 会的话，护栏一当场失效。

    实现契约：哈希 `dataclasses.fields(_Facts)` 的**全集**（而非手写字段名列表）——手写列表会在有人给
    `_Facts` 加字段时静默漏掉，而这正是「fp 字段集 ≡ 分支表输入集」这条不变式最容易被破坏的地方。

    **`_Clock` 不进 fp**（见 `_Clock` docstring）。`facts.subject` 进 fp 是无害的（同 subject 内恒定）。
    """
    payload = {field.name: _stable(value=getattr(facts, field.name)) for field in fields(_Facts)}
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _phase_of(*, verdict: _Verdict, facts: _Facts) -> str:
    """# Spec-0066/T2: 把一个 `_Verdict` 归一成墙钟计时的 phase 字符串（纯函数、无 IO）。

    归一逻辑读 `_Verdict`/`_Facts` 类型，故留在 `vigil` 而非 `timing`——保 `timing` 对 `vigil` **零依赖**、
    杜绝循环 import。四值各自的 phase：
      - `IN_FLIGHT` → `in-flight`（生产者视角：有别的 worker 在干，看不出干哪一步）；
      - `TERMINAL`  → 据 `facts` 细分 `merged`/`closed`/`needs-human`（收口原因，供报告区分）；
      - `QUIET`     → `reason`（`awaiting-blockers`/`-mergeability`/`-ci`/`-effect`，天然细分合并段的等待相）；
      - `ACTIONABLE`→ `action`（`solve`/`rebase`/`fix-ci`/`e2e`/`review-or-fix`/`merge`/`reply`——worker 以
        `in_flight=False` 调 `_classify`，故 `_reconcile` 记的是**具体动作**，把生产者的泛 in-flight 解开）。
    """
    if verdict.kind == _IN_FLIGHT:
        return _IN_FLIGHT
    if verdict.kind == _TERMINAL:
        if facts.merged:
            return _PHASE_MERGED
        if facts.closed:
            return _PHASE_CLOSED
        return _PHASE_NEEDS_HUMAN
    if verdict.kind == _QUIET:
        return verdict.reason or _QUIET
    return verdict.action or _ACTIONABLE


def _record_timing(
    *, work_dir: Path, subject: str, facts: _Facts, verdict: _Verdict, now: datetime
) -> None:
    """# Spec-0066/T2: 旁路盖一枚阶段戳（`timing.record`）。**容错**：任一失败绝不影响守夜推进。

    从 subject 解出 issue/pr 归属（`issue:5` → issue=5,pr=facts.pr_number；`pr:12` → pr=12,issue=None：
    裸 PR 无 issue 归属）。不改任何返回值/控制流/fp——只旁路 append（对齐「只富化不回归」）。整体裹 try：
    连 `_split_subject`/`_phase_of` 也不许把一条计时的失败冒泡进主流程。
    """
    try:
        kind, number = _split_subject(subject=subject)
        issue = number if kind == _KIND_ISSUE else None
        pr = number if kind == _KIND_PR else facts.pr_number
        timing.record(
            work_dir=Path(work_dir),
            subject=subject,
            issue=issue,
            pr=pr,
            phase=_phase_of(verdict=verdict, facts=facts),
            now=now,
        )
    except Exception:  # noqa: BLE001 —— 旁路容错：计时失败绝不影响守夜推进
        return


def _watchdog(
    *, verdict: _Verdict, clock: _Clock, thresholds: dict[str, int | None], now: datetime
) -> bool:
    """护栏二：QUIET 状态的 age 超过**该成因的**阈值 → 该 park（打 needs-human）。返回是否该 park。

    「什么都没变」本身就可能是故障——CI 永不启动（workflow 没匹配 / base 不是 main / Actions 被禁）在日志里
    跟「正常等 CI」长得一模一样。而**判断「卡了多久」不需要任何本地记忆**：`age = now − last_progress_at`，
    每个 GitHub 对象都自带时间戳，head 一变计时自动归零。重启 / 丢库 / 换机器都不影响。

    阈值按 `verdict.reason` 分档（`_WATCHDOG_DEFAULTS`，可被 `run_vigil(watchdog_thresholds=…)` 覆盖）——
    四个成因的自然时长差两个数量级。阈值为 `None` = 该成因不看门（`_AWAITING_BLOCKERS` 默认如此：上游有
    自己的看门狗，重复计时只会误杀）。IN_FLIGHT / TERMINAL / ACTIONABLE 一律返回 False（不是本函数的职责）。

    **阈值宁可给宽。** 设窄了会把正常在跑的 CI 误 park，比不看门更糟；而 park 只是「打个 label + 贴条诊断」、
    完全可逆（人摘掉 label 系统立刻复活），晚叫人的代价远小于误杀。
    """
    if verdict.kind != _QUIET:
        return False
    threshold = thresholds.get(verdict.reason or "")
    if threshold is None or clock.last_progress_at is None:
        return False
    return (now - clock.last_progress_at).total_seconds() > threshold


# --------------------------------------------------------------------------------------------------
# 感知的纯辅助（GitHub 原值 → facts 枚举；评论 → 戳；label → 裁决）。全部无 IO。
# --------------------------------------------------------------------------------------------------


def _split_subject(*, subject: str) -> tuple[str, int]:
    """`"issue:5"` → `("issue", 5)`。subject 是 TEXT 而非 INTEGER 的全部理由（裸 PR 是一等公民）。"""
    kind, _, raw = subject.partition(":")
    if kind not in (_KIND_ISSUE, _KIND_PR) or not raw.isdigit():
        raise ValueError(f"非法 subject：{subject!r}（应形如 issue:5 / pr:12）")
    return kind, int(raw)


def _mergeable_state(*, snapshot: github.PRSnapshot) -> str:
    """GitHub 的 `mergeable` / `mergeStateStatus` 两原值 → `clean | dirty | unknown` 三值。

    `BEHIND`（base 前移了但没冲突）也归 `dirty`：两者的处置动作是同一个——先动分支（`_act` 的 rebase 支
    先试机械 `update_branch`，不行再下放 agent 解冲突），且都不该在动之前读 CI（旧 head 上的 CI 无意义）。
    """
    if snapshot.mergeable == "CONFLICTING" or snapshot.merge_state_status in ("DIRTY", "BEHIND"):
        return _MERGE_DIRTY
    if snapshot.mergeable == "MERGEABLE":
        return _MERGE_CLEAN
    return _MERGE_UNKNOWN


def _ci_state(*, snapshot: github.CheckSnapshot) -> str:
    """check 快照 → `success | failure | pending | none`。**零个 check 是 `none`，不是 `success`。**

    `github.check_status` 把「无 check」归成 pass（无 CI 的仓库照常放行）——守夜不能沿用：一个 workflow
    从未启动的 PR（base 不是 main / Actions 被禁 / workflow 没匹配）会被读成「绿了」→ 直接合并一份没跑过
    CI 的代码。故这里靠 `count` 把它分出来，落 `QUIET(awaiting-ci)`，超时由看门狗叫人（护栏二）。
    """
    if snapshot.count == 0:
        return _CI_NONE
    if snapshot.state == "fail":
        return _CI_FAILURE
    if snapshot.state == "pending":
        return _CI_PENDING
    return _CI_SUCCESS


def _latest_e2e_sha(*, comments: list[github.Comment]) -> str | None:
    """从 PR 评论里取**最新一条** e2e 证据评论的溯源戳 head sha；无证据 → None（分支⑨ 判该补）。"""
    stamped = [comment for comment in comments if _E2E_MARKER in comment.body]
    if not stamped:
        return None
    latest = max(stamped, key=lambda comment: comment.created_at)
    tail = latest.body.split(_E2E_MARKER, 1)[1]
    return tail.split("-->", 1)[0].strip() or None


def _latest_is_ours(*, comments: list[github.Comment]) -> bool:
    """最新一条评论是不是我方签名的（无评论 → True，即「人没有新话」）。**不存 comment id**（见 `_Facts`）。"""
    if not comments:
        return True
    latest = max(comments, key=lambda comment: comment.created_at)
    return identity.parse_agent_id(body=latest.body) is not None


def _review_from_labels(*, labels: set[str]) -> tuple[str | None, str | None]:
    """从 `review-*:<sha7>` label 解析裁决 `(state, commit_sha7)`。裸 `review-approved`（无 sha）**不被承认**。

    同时挂着两种裁决时（审过后又被打回），**CHANGES_REQUESTED 优先**——分支⑩⑪ 里「要改」永远压过「可合」。
    """
    changes = _label_sha(labels=labels, prefix=_LABEL_REVIEW_CHANGES_PREFIX)
    if changes is not None:
        return _REVIEW_CHANGES_REQUESTED, changes
    approved = _label_sha(labels=labels, prefix=_LABEL_REVIEW_APPROVED_PREFIX)
    if approved is not None:
        return _REVIEW_APPROVED, approved
    return None, None


def _label_sha(*, labels: set[str], prefix: str) -> str | None:
    """取带 `prefix` 的 label 里嵌的 sha7；无该 label、或 sha 段为空（裸 label）→ None。"""
    for label in sorted(labels):
        if label.startswith(prefix):
            sha = label[len(prefix) :].strip()
            if sha:
                return sha
    return None


def _short(*, sha: str | None) -> str | None:
    """40 位 head sha → label 里嵌的 sha7（None 透传）。"""
    return None if sha is None else sha[:_SHA_LABEL_LEN]


def _stable(*, value: Any) -> Any:
    """fp 的稳定序列化：frozenset 定序成 list，其余原样（datetime 不会进来——`_Clock` 不进 fp）。"""
    if isinstance(value, frozenset):
        return sorted(value)
    return value


def _latest_ts(*, stamps: list[str]) -> datetime | None:
    """一堆 GitHub ISO 时间戳 → 最新的那个（全空 → None，看门狗据此不看门）。"""
    parsed = [moment for stamp in stamps if (moment := _parse_ts(stamp=stamp)) is not None]
    return max(parsed) if parsed else None


def _parse_ts(*, stamp: str) -> datetime | None:
    """GitHub ISO 8601（`…Z`）→ aware datetime；空串 / 坏格式 → None（不抛，感知层不该因脏数据崩）。"""
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None


# --------------------------------------------------------------------------------------------------
# DB 队列层（SQLite + flock）：建表 / 连接 / 入队 / 原子领取 / 凭 flock 判死回收 / 收工删行 / 失败重排 / 排空。
# --------------------------------------------------------------------------------------------------


def _init_db(*, db_path: Path) -> None:
    """建 `work_queue` 表（幂等 `IF NOT EXISTS`）+ 开 WAL + 建 `claims/` 目录。`run_vigil` 起头调一次。

    WAL 让并发读不挡单写（https://www.sqlite.org/wal.html）；表结构见 `_SCHEMA`。父目录 `.openagents/`
    与 runtime-state.json 同置，不存在则建。
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    (db_path.parent / _CLAIMS_DIRNAME).mkdir(parents=True, exist_ok=True)
    conn = _connect(db_path=db_path)
    try:
        conn.executescript(_SCHEMA)
    finally:
        conn.close()


def _connect(*, db_path: Path) -> sqlite3.Connection:
    """开一条**本线程私有**的 SQLite 连接（sqlite3 连接默认不跨线程共享——每 worker / 生产者各开各的）。

    `isolation_level=None`（自动提交，手动 `BEGIN IMMEDIATE` 控事务）+ `busy_timeout=_BUSY_TIMEOUT_MS`
    （抢写锁抢不到时自旋而非立刻报错）+ WAL + `row_factory=sqlite3.Row`（按列名取值）。
    """
    conn = sqlite3.connect(str(db_path), isolation_level=None, timeout=_BUSY_TIMEOUT_MS / 1000)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def _enqueue(*, conn: sqlite3.Connection, subject: str, priority: int, now: datetime) -> bool:
    """把一个 subject 入队：`INSERT OR IGNORE INTO work_queue(subject, …)`。新入队 True，已在表中 False。

    **不做变更检测**：生产者每 tick 对每个 ACTIONABLE 的 subject 无脑调用它，重复入队由 `subject` 的 UNIQUE
    约束吃掉（no-op）。这就是 level-triggered 的落地方式——幂等让「重算一遍」永远安全。

    `subject` UNIQUE 一根柱子同时给出**去重**、**同-subject 串行**（一个 subject 最多一行 → 被领走后再插入
    仍是 no-op → 同一个 PR 上永远只有一个 agent）、**幂等**。故没有 `dedup_key`，`_claim_next` 也不需要
    `NOT EXISTS` 子查询。

    `priority` 取自 `priority_fn`（越大越先）；`enqueued_at=now.isoformat()` 作等优先级下的 FIFO tie-break。

    **已在队里的行要刷新 `priority`**（`ON CONFLICT … DO UPDATE`，仅限还没被领走的 `queued` 行）：一个 subject
    在排队期间可能从 `solve`(1) 变成 `merge`(5)（上游合了、CI 绿了），若把优先级冻结在入队时刻，「先收尾在制品、
    再开新工」的排序就是按**过时的**权重排的。`enqueued_at` 不刷新——它是 FIFO tie-break，刷了会让久候的行
    永远排在后面（饿死）。`claimed` 行不动：它已经在跑，改它的优先级没有意义。
    """
    existing = conn.execute(
        "SELECT id, status, priority FROM work_queue WHERE subject=?", (subject,)
    ).fetchone()
    if existing is None:
        conn.execute(
            "INSERT OR IGNORE INTO work_queue (subject, priority, enqueued_at, status) "
            "VALUES (?, ?, ?, 'queued')",
            (subject, priority, now.isoformat()),
        )
        return True
    if existing["status"] == "queued" and existing["priority"] != priority:
        conn.execute(
            "UPDATE work_queue SET priority=? WHERE id=? AND status='queued'",
            (priority, existing["id"]),
        )
    return False


def _claim_next(
    *,
    conn: sqlite3.Connection,
    work_dir: Path,
    worker_id: str,
    now: datetime,
) -> tuple[dict, int] | None:
    """**原子领取 + 取存活证明**：领队首 → 对 `claims/{subject}.lock` 取 flock → 返回 `(row, fd)`。空返 None。

        BEGIN IMMEDIATE;
        UPDATE work_queue
           SET status='claimed', worker=?, worker_pid=?, claimed_at=?, attempts=attempts+1
         WHERE id = (SELECT id FROM work_queue
                      WHERE status='queued'
                      ORDER BY priority DESC, enqueued_at ASC
                      LIMIT 1)
         RETURNING *;                     -- SQLite 3.35+
        -- 拿到行之后、COMMIT 之前：flock(LOCK_EX|LOCK_NB) 抢到 → COMMIT；抢不到 → ROLLBACK 跳过
        COMMIT;

    - `WHERE status='queued'` + **`BEGIN IMMEDIATE`** → **exactly-once 领取**：两 worker 并发领同一行时，
      序列化后第二个 `UPDATE` 匹配不到、返回空。这正是 GitHub label 做不到的（无 CAS，见模块头）。SQLite 无
      `SKIP LOCKED`，`BEGIN IMMEDIATE`（立刻取写锁）是它的单机等价物。
    - `ORDER BY priority DESC, enqueued_at ASC` → **领取时定序**（求值发生在此刻，不冻结在入队时刻，久候行的
      优先级不失真）。
    - **flock 与行同生共死** → 回收的正确性：`_reclaim_dead` 凭「抢不抢得到这把锁」判持有者死活，不猜、不设
      阈值。**返回的 fd 必须一路持到收工**（`_mark_done` / `_requeue_or_park` 负责 close）——`close` 任何一个
      指向该 open file description 的 fd 都会释放锁，一个不小心的 `with open(...)` 就把存活证明提前丢掉，让
      自己的行被别人回收走 → **静默双跑**。

    **没有 `NOT EXISTS` 同-subject 子查询**——互斥已由 `subject UNIQUE` 在**入队时**结构性保证（一个 subject
    根本不可能有两行），领取时再查一次是纯冗余。这是「一行 = 一个 subject」相对「一行一事件」的直接红利。

    `attempts` **在领取时 +1**（不是失败时）：崩溃的活即便被 `_reclaim_dead` 反复回收，也会在 `_MAX_ATTEMPTS`
    处被 park、不无限占槽——这是唯一能发现「agent 没能收工」的机制（它在 GitHub 上零痕迹）。
    """
    skipped: list[int] = []
    while True:
        placeholders = ",".join("?" * len(skipped))
        exclude = f" AND id NOT IN ({placeholders})" if skipped else ""
        conn.execute("BEGIN IMMEDIATE")
        fd: int | None = None
        try:
            row = conn.execute(
                "UPDATE work_queue "
                "   SET status='claimed', worker=?, worker_pid=?, claimed_at=?, attempts=attempts+1 "
                " WHERE id = (SELECT id FROM work_queue "
                f"              WHERE status='queued'{exclude} "
                "              ORDER BY priority DESC, enqueued_at ASC "
                "              LIMIT 1) "
                " RETURNING *",
                (worker_id, os.getpid(), now.isoformat(), *skipped),
            ).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return None
            fd = _try_lock(path=_lock_path(work_dir=work_dir, subject=row["subject"]))
            if fd is None:
                # 锁被别人持着（回队/回收与释锁之间的亚毫秒窗口）：**跳过这一行、接着看下一行**，不能直接
                # 返回 None——返回 None 会被 worker 读成「队列空了」而去睡 `_WORKER_POLL_SECONDS`，于是队首
                # 一行的瞬时锁冲突把**所有** worker 全挡在门外（队头阻塞）。宁可这一轮不领它，也不双跑。
                conn.execute("ROLLBACK")
                skipped.append(int(row["id"]))
                continue
            conn.execute("COMMIT")
            return dict(row), fd
        except BaseException:
            # fd 已到手却没能 COMMIT：必须 close，否则锁留在本进程手里而行是 queued → 这一行**再也领不走**
            # （`_claim_next` 永远抢不到它的锁，`_reclaim_dead` 只管 claimed 行）→ 整个队列在它后面饿死。
            if fd is not None:
                _close_quietly(fd=fd)
            conn.execute("ROLLBACK")
            raise


def _reclaim_dead(*, conn: sqlite3.Connection, work_dir: Path) -> int:
    """**凭 flock 判死**：`claimed` 行的锁抢得到 ⇒ 内核已回收持有者的锁 ⇒ 它确已死 → 行回 `queued`。返回回收数。

        fd = open(claims/{row.subject}.lock)
        try flock(fd, LOCK_EX | LOCK_NB)
        ├─ 抢到      → 内核说「没人持有」→ 持有者**确已死** → UPDATE … status='queued' → 立刻 close(fd)
        └─ EWOULDBLOCK → 内核说「有人持有」→ 持有者**确实活着** → **永不回收**（无论它跑了多久）

    **这是整个并发模型里唯一一处「判断别人是否还活着」，而它不做判断——它问内核。** 本函数**没有任何阈值
    参数**，因此没有任何可以调错的旋钮：双跑是结构性的零，不是「租约设得够长」的小概率。

    `kill -9` / OOM / 段错误 / 断电重启全都算「死」（flock 绑 open file description，进程一死内核释放）。
    「活着但卡死」不归这里管——回收一个活着的持有者的行，定义上就是双跑；那由 `_act` 硬超时 + IN_FLIGHT
    告警兜（见模块头）。生产者 tick 起头调；`attempts` 已在领取时 +1，故毒丸活反复崩也会在 `_MAX_ATTEMPTS`
    处被 park。
    """
    rows = conn.execute("SELECT id, subject FROM work_queue WHERE status='claimed'").fetchall()
    reclaimed = 0
    for row in rows:
        fd = _try_lock(path=_lock_path(work_dir=work_dir, subject=row["subject"]))
        if fd is None:
            continue  # 内核：持有者活着 → 永不回收（哪怕它已超 IN_FLIGHT 告警阈值）
        try:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                "UPDATE work_queue "
                "   SET status='queued', worker=NULL, worker_pid=NULL, claimed_at=NULL "
                " WHERE id=? AND status='claimed'",
                (row["id"],),
            )
            conn.execute("COMMIT")
            if (
                cursor.rowcount
            ):  # 0 行 = 持有者在 SELECT 与此之间正常收工删了行 → 什么也没回收，别谎报
                reclaimed += 1
                _log(message=f"♻ 回收死持有者的认领：{row['subject']}（flock 抢得到 ⇒ 进程已死）")
        finally:
            os.close(fd)
    return reclaimed


def _sweep_stalled(
    *,
    conn: sqlite3.Connection,
    work_dir: Path,
    seen_locked: dict[str, datetime],
    now: datetime,
    agent_id: str,
) -> int:
    """**queued 行的锁被人持着、且跨 tick 一直持着 ⇒ 存活证明泄漏了** → park 交人。返回本轮 park 数。

    这是 `hold_fd`（把 flock 的 fd 传给 agent 子进程继承）的**必要配套**。继承换来的是「孤儿 agent 还在跑 →
    行不会被回收 → 无双跑」，但代价是这把锁也会随之传给 agent 的**孙子**进程（`pass_fds` 在子进程里清掉了
    CLOEXEC，而 agent 不是 python，不会替我们关）：agent 若留下一个长命的孙子（MCP server、它自己起的后台
    dev server），那个孙子会一直持着锁。

    **没有这道闸的话，那就是一个永久的、静默的停摆**，而不是「卡住等人来收」：
    - `_reclaim_dead` 只扫 `claimed` 行——这行是 `queued`，看不见；
    - IN_FLIGHT 告警看 `claimed_at`——这行没有，看不见；
    - QUIET 看门狗只对 QUIET 裁决生效——这 subject 是 ACTIONABLE（正因如此才入的队），看不见；
    - `_claim_next` 每轮抢不到锁就静默 `skipped`，`_hang` 于是报「前沿空」——**一句谎话**。

    **判据必须扛得住并发，而不只是「看一眼」**——park 是不可逆的（healthy subject 被误 park = 亲手制造它本要
    根除的那种永久停摆），故这里对每一条误判路径都设了闸：

    1. **「锁自由」= 只是在排队等槽**（K 满 / 优先级靠后）→ 放过。长队列不是故障。
    2. **跨 tick 才算数**（`seen_locked`）。「queued 且锁被持着」有**合法的瞬时**形态：`_requeue_or_park` /
       `_reclaim_dead` 都是先 `UPDATE … status='queued'`（自动提交，别的连接立刻看得见）、再 `os.close(fd)`,
       两步之间那一行正是「queued + 锁还持着」。**不能用 `enqueued_at` 的年龄来排除它**——`enqueued_at`
       在回队时**故意不刷新**（防饿死），一个跑了 5 分钟的活回队时天生就是「老」的，一眼就会被误判成泄漏。
       改判「**同一行连续两次 tick 都被看见锁着**」：那个交接窗口是微秒级的，活不过一次 tick 间隔；泄漏则永远。
    3. **开口之前先把行抢下来**（`_park_stalled` 在 `BEGIN IMMEDIATE` 里 `DELETE … AND status='queued'`，
       抢不到就一个字都不说）。上面那次探锁是在快照上做的，而 park 要发两次 `gh`（**数秒**）——这期间一个
       worker 完全可能正常领走**另一行**并锁上它，轮到我们探它时锁当然是「被持着」的。只「复核一下再发 gh」
       是不够的：复核到发完 `gh` 之间那几秒里泄漏进程可能恰好死掉、锁一自由 worker 就合法领走并开跑，我们那条
       `needs-human` 于是落在一个**健康且正在被执行**的 subject 上 → 下一圈 `_classify` 判 TERMINAL → worker
       掉头就走 → **永久停摆，正是本函数要防的东西**。行删得掉、话收不回，所以顺序只能是「先删行、再说话」。
    4. **删行即互斥**（`_claim_next` 只认 `queued`）。这与 `_requeue_or_park`「先落 label 再删行」相反——那边
       删的是自己的 `claimed` 行（没人能抢，丢 label 却会让 `attempts` 归零、无限重派烧 LLM）；这边删的是一个
       谁都能领的 `queued` 行（丢 label 只是下一 tick 由 `_intake` 重新推导、重新计时——有节流、零 LLM）。
       详见 `_park_stalled`。
    5. **单行失败就地隔离**：`gh` 429 不能掀掉整个生产 tick（否则 `_intake` 与全部感知一起停摆——一个泄漏的行
       把整条流水线拖死，比它自己卡住坏得多）。
    """
    rows = conn.execute("SELECT id, subject FROM work_queue WHERE status='queued'").fetchall()
    parked = 0
    still_locked: set[str] = set()
    for row in rows:
        subject = row["subject"]
        path = _lock_path(work_dir=work_dir, subject=subject)
        fd = _try_lock(path=path)
        if fd is not None:
            os.close(fd)  # 闸 1：锁自由 → 只是排队等槽，一切正常
            continue
        still_locked.add(subject)
        first = seen_locked.setdefault(subject, now)
        held_seconds = (now - first).total_seconds()
        if held_seconds <= _STALE_LOCK_SECONDS:
            continue  # 闸 2：可能只是回队/回收的交接窗口——它活不过一次 tick，下轮再看
        try:
            parked += _park_stalled(
                conn=conn,
                task_id=int(row["id"]),
                subject=subject,
                path=path,
                held=held_seconds,
                agent_id=agent_id,
            )
        except Exception as exc:  # noqa: BLE001 —— 闸 5：一行 park 不成，不许拖垮整轮生产
            # 行或者还在（DELETE 就失败了、已回滚），或者已经没了（label 那步才失败）——两种都由下一 tick 的
            # `_intake` 从 GitHub 现态收敛回来，重新计时、重新 park。这里只管不让它掀掉整轮生产。
            _log(message=f"✗ {subject}：交人未落地（下轮由 _intake 重新推导并重试）：{exc}")
    for subject in set(seen_locked) - still_locked:
        seen_locked.pop(subject, None)  # 锁放了/行没了 → 忘掉它，重新计时
    return parked


def _park_stalled(
    *,
    conn: sqlite3.Connection,
    task_id: int,
    subject: str,
    path: Path,
    held: float,
    agent_id: str,
) -> int:
    """`_sweep_stalled` 判定泄漏后的落地：**先用 DELETE 把行抢下来，赢了才开口说话**。

    **删行必须发生在 `gh` 之前**，这一条和 `_requeue_or_park` 的顺序（先落 label 再删行）正好相反，是故意的：

    - 那边删的是一个 **`claimed`** 行——它是本 worker 自己的，没有别人能领走，所以拿着它去发 `gh` 不伤人；
      而那条路上丢了 label 的代价是 `attempts` 归零、无限重派、白烧 LLM，所以 label 必须先落地。
    - 这边删的是一个 **`queued`** 行——它**随时可能被 worker 合法领走**。`_claim_next` 只认 `queued`，所以
      「删掉」就是把它从所有 worker 的视野里拿走，是这里唯一真正的互斥手段。先发 `gh`（两次网络往返、以秒计）
      再删，就留出一个窗口：泄漏进程恰在此刻死掉 → 锁自由 → worker 合法领走并开跑 → 我们那条 `needs-human`
      落在一个**健康且正在被执行**的 subject 上 → 下一圈 `_classify` 判 TERMINAL → worker 掉头就走、行被删 →
      这个 issue **再也不会被动手**。删行的守卫救得了行，救不了 label：话一旦说出去就收不回来。

    两边的失败代价不对称，所以顺序相反：这里丢了 label 只是「行没了、label 没打」→ 下一 tick 的 `_intake`
    从 GitHub 现态把它重新推导出来（锁还被占着，仍领不走）→ 再等 `_STALE_LOCK_SECONDS` 重新 park。一次
    **有节流、零 LLM** 的重试而已；而误 label 一个健康 subject 是**不可逆的永久停摆**。
    """
    conn.execute(
        "BEGIN IMMEDIATE"
    )  # 与「worker 领取」串行化（`_claim_next` 也走 BEGIN IMMEDIATE）：抢行，不是问一句
    try:
        cur = conn.execute("DELETE FROM work_queue WHERE id=? AND status='queued'", (task_id,))
        won = cur.rowcount == 1
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    if not won:
        # 探锁之后、动手之前被 worker 正常领走了（那把锁是它的，天经地义）→ 收手，一个字都不许说。
        return 0
    _park_needs_human(
        subject=subject,
        body=(
            f"⏸ openagents 守夜：`{subject}` 已排在队里、且它的存活证明 `{path}` 被人持着超过 "
            f"{int(held)}s —— 而没有任何 worker 在跑它，它永远领不走。\n\n"
            "几乎可以肯定是上一次 agent 调用**泄漏了长命子进程**（MCP server、它自己起的后台服务），"
            "那个进程继承了锁的 fd 并一直持着。请查出并清掉它：\n\n"
            f"```\nlsof {path}\n```\n\n"
            "清掉后摘掉本 label，守夜会自动重新接管。"
        ),
        agent_id=agent_id,
    )
    _log(message=f"⏸ {subject}：存活证明被泄漏进程占着（queued 却领不走）→ 交人")
    return 1


def _mark_done(*, conn: sqlite3.Connection, task_id: int, fd: int) -> None:
    """收工：**先删行、再释放锁**（顺序即正确性）。

    **必须是 DELETE，不能是 `status='done'`**——`subject` 有 UNIQUE 约束，留着 done 行会让该 subject
    **永远无法再入队** → PR 死锁。这不是风格，是正确性。

    **必须先删行后 `close(fd)`**：反过来会开一个窗口——锁已放、行还挂着 `claimed` → 另一个 `_reclaim_dead`
    抢到锁、判「死了」、把行打回 `queued` → 被重领 → **双跑**。先删行再释锁，最坏是崩在两步之间：行已删、
    锁由内核释放，干净收场。

    done 的真相在 GitHub（PR merged / 评论已回 / 流水线已推进），队列行只是调度缓存；该 subject 后续若又该
    动手（新评论、CI 变红、上游合并），生产者从 GitHub 现态重新 `_enqueue` 一行。

    **fd 的所有权：进了这个函数就归它**——`finally` 保证 close 恰好一次（`_finish` 据此不再兜底重关；
    重复 close 一个已被别的线程复用的 fd 号 = 放掉**别人**的 flock → 那个还在跑的 worker 被判死 → 双跑）。
    """
    try:
        conn.execute("DELETE FROM work_queue WHERE id=?", (task_id,))
    finally:
        os.close(fd)


def _requeue_or_park(
    *,
    conn: sqlite3.Connection,
    task_id: int,
    subject: str,
    fd: int,
    agent_id: str,
) -> None:
    """领取后失败（`_reconcile` 抛，含 `_act` 硬超时）的收尾：`attempts < _MAX_ATTEMPTS` → 回 queued；到顶 →
    删行 + park。**同样先写行、后释锁。**

    park = 删该行 + 给该 subject 打 `needs-human`（→ 下一 tick `_classify` 判 TERMINAL → 轮询停止）。防毒丸
    活无限重试霸占槽。`attempts` 在 `_claim_next` 领取时已累加，这里只读它判上限。

    这是**三道护栏里唯一需要计数的那道**：agent 崩 / 被 kill 时它没盖 attempt 戳、也没刷新任何 GitHub 时间
    戳 → fp 判不出、age 也判不出 → 只能在队列行里数（见模块头）。**持有者自己走这条路**（不是别人来回收），
    故 claimed 行永不成孤儿。

    **到顶时：先把 needs-human 落到 GitHub，再删行。** 反过来（先删行、后发 `gh`）会让一次 429/网络抖动把
    「park」悄悄变成「重新派发」：行没了、label 也没打上，下一个 tick 生产者重新感知 → 还是 ACTIONABLE →
    重新入队 → **`attempts` 从 0 起算** → 毒丸活永远到不了上限，白烧模型。先打标的话，`gh` 抛出时行仍是
    `claimed`、锁已还给内核 → `_reclaim_dead` 回收 → 重来一遍（幂等），最坏多跑一轮，不会丢掉「交人」。

    **fd 的所有权：进了这个函数就归它**——`finally` 保证 close 恰好一次（`_finish` 据此不再兜底重关；重复
    close 一个已被别的线程复用的 fd 号 = 放掉**别人**的 flock → 那个还在跑的 worker 被判死回收 → 双跑）。
    """
    try:
        row = conn.execute("SELECT attempts FROM work_queue WHERE id=?", (task_id,)).fetchone()
        attempts = int(row["attempts"]) if row is not None else _MAX_ATTEMPTS
        if attempts < _MAX_ATTEMPTS:
            conn.execute(
                "UPDATE work_queue "
                "   SET status='queued', worker=NULL, worker_pid=NULL, claimed_at=NULL WHERE id=?",
                (task_id,),
            )
            _log(message=f"↻ {subject}：本次认领未收工（第 {attempts} 次），已回队重排")
            return
        _park_needs_human(  # 先落地交人（抛出 → 行留 claimed，回收兜底），再删行
            subject=subject,
            body=(
                f"⏸ openagents 守夜：`{subject}` 连续 {attempts} 次认领未收工"
                "（agent 崩溃 / 被 kill / 超时），已交人接手。\n\n"
                "摘掉本 label 即可让守夜重新接管（谓词无历史，自动复活）。"
            ),
            agent_id=agent_id,
        )
        conn.execute("DELETE FROM work_queue WHERE id=?", (task_id,))
    finally:
        os.close(fd)


def _drain_queue(
    *,
    db_path: Path,
    work_dir: Path,
    seen_locked: dict[str, datetime],
    now_fn: Callable[[], datetime],
    stop_event: threading.Event,
    agent_id: str,
) -> None:
    """`once=True` 的排空：轮询到 `work_queue` 无 queued 且无 claimed 行才返回（给测试确定性同步语义）。

    生产者单 tick 入的活 + 其占的 claimed 全被 worker 消费/删净即排空。轮询间隔 `_WORKER_POLL_SECONDS`；
    `stop_event`（如测试中途叫停）也解除等待。K=1 顺序 drain、K>1 由此收口。

    **有硬上限 `_DRAIN_MAX_SECONDS`**：`once=True` 是 CLI 与 e2e 的路径，它不能有「永不返回」这种结局。没有
    上限时，任何一行卡住（worker 死在收尾、agent 挂在一个不返回的调用上）都会让 `oa vigil --once` **永远挂着**
    ——而排空本就是个尽力而为的同步点，不是正确性来源（真相在 GitHub，下一次 tick 会从现态重新推）。到点则记
    日志返回，把剩下的活留在队里（下次启动 `_reclaim_dead` + level-triggered 重算自会接上）。
    """
    conn = _connect(db_path=db_path)
    deadline = time.monotonic() + _DRAIN_MAX_SECONDS
    try:
        while not stop_event.is_set():
            pending = conn.execute("SELECT COUNT(*) AS n FROM work_queue").fetchone()["n"]
            if not pending:
                return
            if time.monotonic() >= deadline:
                _log(message=f"⏱ 排空超 {_DRAIN_MAX_SECONDS}s 仍有 {pending} 行未消费，本次先返回")
                return
            # 排空期间也要扫「存活证明泄漏」：那种行**永远**领不走，只在 tick 开头扫一次的话，`--once`
            # 会在这里干等满 `_DRAIN_MAX_SECONDS`（1h）才返回——CLI 与 e2e 都走这条路，不能这么挂着。
            # 扫不动不等于排不空：守夜主循环把 `_producer_tick` 整个包在 except 里（第一要务是活着进下一轮），
            # 排空这条路上没有那层网——一个 EMFILE / claims 目录被 chmod 掉，就会从这里逃出去打死 `--once`。
            try:
                _sweep_stalled(
                    conn=conn,
                    work_dir=Path(work_dir),
                    seen_locked=seen_locked,
                    now=now_fn(),
                    agent_id=agent_id,
                )
            except Exception as exc:  # noqa: BLE001
                _log(message=f"✗ 排空期扫陈锁失败（不影响排空，继续等）：{exc}")
            stop_event.wait(_WORKER_POLL_SECONDS)
    finally:
        conn.close()


def _lock_path(*, work_dir: Path, subject: str) -> Path:
    """`claims/{subject}.lock` 的落处（`:` 换 `-`，文件名安全）。锁文件本身无状态——状态在内核。"""
    return Path(work_dir) / ".openagents" / _CLAIMS_DIRNAME / f"{subject.replace(':', '-')}.lock"


def _try_lock(*, path: Path) -> int | None:
    """对锁文件取 `flock(LOCK_EX | LOCK_NB)`：抢到返回 fd（**调用方负责 close**），EWOULDBLOCK 返回 None。

    **必须是 `fcntl.flock`，不能是 `fcntl.lockf`（POSIX `F_SETLK`）**：后者的锁是 **per-process** 的——同一
    进程内两个 fd 对同一文件加锁**不互斥**。本模块是「一个进程 K 条 worker 线程」，用 `lockf` 会让 worker
    之间的互斥**静默失效**（`tests/test_recipe_vigil.py` 有一条「同进程两 fd 互斥」的断言专门钉死这点）。
    flock 的锁绑在 open file description 上，同进程不同 `open()` 之间照样冲突——这正是我们要的。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(fd)
        if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK):
            return None
        raise
    return fd


# --------------------------------------------------------------------------------------------------
# 生产者（主线程）：reclaim → intake（准入面，agentic）→ 逐 subject sense/classify → 入队 or 看门。
# --------------------------------------------------------------------------------------------------


def _producer_tick(
    *,
    backend: Any,
    state: RuntimeState,
    work_dir: Path,
    config: agent_config.AgentConfig,
    agent_id: str,
    db_path: Path,
    priority_fn: Callable[..., Any],
    thresholds: dict[str, int | None],
    seen_locked: dict[str, datetime],
    now: datetime,
) -> int:
    """生产者单 tick：**只生产、不领活**。返回本 tick 新入队数。

        _reclaim_dead                                     # 凭 flock 判死，回收死持有者的行
        _sweep_stalled                                    # queued 行的锁被泄漏进程占着 → park 交人
        _intake                                           # 准入面：三态审 → ready → curator 排边 → POST
        for subject in _subjects():
            observed = _sense(subject)                    # 唯一的 GitHub 读
            verdict  = _classify(observed.facts)          # 纯函数
            fp       = _fingerprint(observed.facts)       # 纯函数
            IN_FLIGHT → claimed_at 超龄? _park（**只告警、绝不动行**）
            TERMINAL  → 略过
            ACTIONABLE 且 _has_attempt_stamp(fp) → 降级为 QUIET(awaiting-effect)   ← 护栏一
            ACTIONABLE            → _enqueue(priority_fn(verdict))
            QUIET                 → _watchdog 说超时？ _park : 略过                ← 护栏二
        入队数 == 0 → _hang

    **护栏一在这里包在 `_classify` 之外**（而不是塞进 `_classify`）：判断「GitHub 上有没有 fp 相同的 attempt
    戳」要读 GitHub，有副作用；`_classify` 必须保持纯，否则它就不能被 `_reconcile` 在 worker 里无成本地反复
    调用。降级后的 QUIET 仍会走看门狗——`awaiting-effect` 有阈值而非立即 park，**不是**为了给模型第二次抽卡
    机会，而是为了吸收**异步生效窗口**（agent push 完但 GitHub API 还返回旧 head 的最终一致性、agent 触发了
    CI rerun 但 check 还没翻 pending）。真进展会落地、fp 会变、旧戳自动作废；真撞墙则超时 park。

    单 subject 感知/入队失败**就地隔离**（记日志、continue）——一个 subject 崩不该让整轮生产停摆。
    """
    conn = _connect(db_path=db_path)
    try:
        _reclaim_dead(conn=conn, work_dir=Path(work_dir))
        _sweep_stalled(
            conn=conn,
            work_dir=Path(work_dir),
            seen_locked=seen_locked,
            now=now,
            agent_id=agent_id,
        )
        _intake(
            backend=backend,
            work_dir=Path(work_dir),
            config=config,
            agent_id=agent_id,
            now=now,
        )

        in_flight = {
            row["subject"]: row["claimed_at"]
            for row in conn.execute(
                "SELECT subject, claimed_at FROM work_queue WHERE status='claimed'"
            ).fetchall()
        }
        enqueued = 0
        quiet_counts: dict[str, int] = {}
        for subject in _subjects(config=config):
            try:
                enqueued += _consider(
                    conn=conn,
                    subject=subject,
                    config=config,
                    work_dir=Path(work_dir),
                    in_flight=in_flight,
                    priority_fn=priority_fn,
                    thresholds=thresholds,
                    quiet_counts=quiet_counts,
                    now=now,
                    agent_id=agent_id,
                )
            except Exception as exc:  # noqa: BLE001 —— 单 subject 失败不拖垮整轮生产
                _log(message=f"✗ {subject}：本轮感知失败，跳过：{exc}")
        if enqueued == 0:
            _hang(
                quiet_counts=quiet_counts,
                in_flight_count=len(in_flight),
                interval=config.interval,
            )
        return enqueued
    finally:
        conn.close()


def _unblock_if_replied(*, observed: _Observed, subject: str) -> _Observed:
    """Spec-0058/T1: needs-human 死锁自愈——人类越水位线回复即撤 label，把 subject 从 TERMINAL 复位续跑。

    `needs-human` 是 agent 的一等出口（`_classify` 分支①），但其唯一撤销路径本是**人手摘 label**——分支①
    短路在分支②（人有新话 → reply）之前，人在被挂 subject 上回复评论却没手摘 label 时 subject 一动不动，
    与决策5（agent 先 comment、人审核后流程续跑）及 park 卡点评论对用户的承诺相悖。这里补上闭环：

    **「人在被挂 subject 上说了话」本身就是解挂信号。** park 的理由评论**必签名**（`_park_needs_human`）且
    恒为 park 那一刻的最后一条，故「最新一条评论不是我方签名」（`facts.latest_comment_is_ours`，`_sense`
    已算出）**恰好等价于**「park 之后有人越过水位线说话」——无需另存 `block_watermark`、无需第二次读。
    撤掉 `needs-human` 后用 `dataclasses.replace` 把它从**本 tick 已读到的 facts** 里剥掉，`_classify` 当轮
    即在「已无 needs-human」现态上从头重判（②reply → ③…⑪ 保守重进整条流水线，无需信任旧证据）。

    **防自触发天然内建**：`latest_comment_is_ours` 靠签名判定（`_latest_is_ours` → `identity.parse_agent_id`），
    机器自己后来盖的任何签名评论都把它顶回 True，解挂不自触发（也让本步骤幂等：撤一次后无更新的无签名评论，
    下一 tick 不再重撤）。撤 label 是唯一状态复位（不写 state 字段）——新栈里 label 本身即终态单一真源，
    人机对话记录留在 GitHub 评论流 + `_log` 行，即 issue 要的 `unblock_detail` 审计落处（GitHub 是领域真相）。
    """
    facts = observed.facts
    if _LABEL_NEEDS_HUMAN not in facts.labels:
        return observed  # 没挂起 → 原样透传
    # 最新是我方签名（含刚 park 的理由）→ 无人越水位线 → 不解挂（幂等 + 防自触发）
    if facts.latest_comment_is_ours:
        return observed
    # 有人在 park 理由评论之后越过水位线说话 → 撤 needs-human，本 tick 即从头重判续跑
    _remove_needs_human(subject=subject)
    _log(message=f"⟳ {subject}：人类越水位线回复，撤 {_LABEL_NEEDS_HUMAN}，复位续跑")
    return replace(observed, facts=replace(facts, labels=facts.labels - {_LABEL_NEEDS_HUMAN}))


def _remove_needs_human(*, subject: str) -> None:
    """Spec-0058/T1: 撤掉 subject 的 `needs-human` label——PR 走 `remove_label`、issue 走 `issue_remove_label`
    （由 `_split_subject` 分流，与 `_park_needs_human` 的打 label 分流对称）。两者皆幂等容错（label 本就不在时
    吞掉视为 no-op），故与人手动摘 label 竞态无害。"""
    kind, number = _split_subject(subject=subject)
    if kind == _KIND_ISSUE:
        github.issue_remove_label(number=number, name=_LABEL_NEEDS_HUMAN)
    else:
        github.remove_label(pr_number=number, name=_LABEL_NEEDS_HUMAN)


def _consider(
    *,
    conn: sqlite3.Connection,
    subject: str,
    config: agent_config.AgentConfig,
    work_dir: Path,
    in_flight: dict[str, Any],
    priority_fn: Callable[..., Any],
    thresholds: dict[str, int | None],
    quiet_counts: dict[str, int],
    now: datetime,
    agent_id: str,
) -> int:
    """单 subject 的生产判定：sense → classify → 护栏一降级 → 入队 / 看门 / 略过。返回本 subject 入队数（0/1）。

    从 `_producer_tick` 里切出来只为让「四值分流」这一段可单测、且错误隔离的 try 边界正好包住一个 subject。

    # Spec-0066/T2: `work_dir`（additive 关键字参）为墙钟计时落盘路径。护栏一降级**前置**到四值分流之前，
    # 使 `_record_timing` 盖到的是降级后的真实等待相（`awaiting-effect`）——`_has_attempt_stamp` 仍只在
    # ACTIONABLE 触发（读 GitHub 的次数与前不变），故这次重排对 IN_FLIGHT/TERMINAL 零行为影响。
    """
    observed = _sense(config=config, subject=subject)
    # Spec-0058/T1: 解挂预处理必须在 `_sense` 之后、`_classify` 之前——撤 label 是副作用（只能生产者侧做），
    # 撤完把 needs-human 从本 tick 已感知的 facts 里剥掉，`_classify` 当轮即在「已无 needs-human」的现态上从头
    # 重判（②reply → ③…⑪ 合并流水线保守重进），满足「守夜一轮内自动续跑」。`_classify` 保持纯函数不动。
    observed = _unblock_if_replied(observed=observed, subject=subject)
    verdict = _classify(facts=observed.facts, in_flight=subject in in_flight)
    fp = _fingerprint(facts=observed.facts)

    if verdict.kind == _ACTIONABLE and _has_attempt_stamp(facts=observed.facts, fp=fp):
        # 护栏一：我在**完全相同的状态**下已经出过手且一个字节没推动 → 别再叫 agent（零 LLM 调用）。
        verdict = _Verdict(kind=_QUIET, reason=_AWAITING_EFFECT)

    # Spec-0066/T2: 生产者旁路盖阶段戳（等待段 awaiting-* / 终态 merged-closed-needs-human / 入队瞬间
    # solve-merge / in-flight）。**旁路**：不改下方任何返回值/控制流/fp，写失败被 `_record_timing` 吞掉。
    _record_timing(
        work_dir=work_dir, subject=subject, facts=observed.facts, verdict=verdict, now=now
    )

    if verdict.kind == _IN_FLIGHT:
        # IN_FLIGHT 超龄 → **只打 needs-human 告警，绝不动行**（回收活着的持有者的行 = 双跑）。
        claimed_at = _parse_ts(stamp=str(in_flight.get(subject) or ""))
        if claimed_at is not None and (now - claimed_at).total_seconds() > _INFLIGHT_ALARM_SECONDS:
            _park(
                facts=observed.facts,
                verdict=verdict,
                clock=observed.clock,
                now=now,
                agent_id=agent_id,
            )
        return 0
    if verdict.kind == _TERMINAL:
        return 0

    if verdict.kind == _ACTIONABLE:
        if _enqueue(
            conn=conn,
            subject=subject,
            priority=priority_fn(verdict=verdict),
            now=now,
        ):
            _log(message=f"⊕ {subject}：{verdict.action} 入队")
            return 1
        return 0

    quiet_counts[verdict.reason or ""] = quiet_counts.get(verdict.reason or "", 0) + 1
    if _watchdog(verdict=verdict, clock=observed.clock, thresholds=thresholds, now=now):
        # park 之前**临门再查一次队列**：`in_flight` 是本 tick 起头拍的快照，而 `_sense` 每个 subject 都要打
        # 好几个 GitHub 往返——快照之后才被 worker 领走的 subject，走到这里仍会被当成「没人管」而挨一发
        # needs-human；那个正在跑的 agent 下一圈 `_sense` 就会读到终态、当场收工（白干一场）。
        if _is_claimed(conn=conn, subject=subject):
            return 0
        _park(
            facts=observed.facts,
            verdict=verdict,
            clock=observed.clock,
            now=now,
            agent_id=agent_id,
        )
    return 0


def _is_claimed(*, conn: sqlite3.Connection, subject: str) -> bool:
    """该 subject **此刻**是否正被某个 worker 持有（现读队列，不看 tick 起头的快照）。"""
    row = conn.execute(
        "SELECT 1 FROM work_queue WHERE subject=? AND status='claimed'", (subject,)
    ).fetchone()
    return row is not None


def _subjects(*, config: agent_config.AgentConfig) -> list[str]:
    """本 tick 要判定的 subject 全集：`ready` 的 open issue + 所有 open PR（含无 issue 归属的裸 PR）。

    裸 PR（`pr:N`）是一等公民——人手开的迭代源 PR 没有 issue，旧串行 vigil 明确支持它（`run.issue_number
    is None`）。这正是队列的 `subject` 列必须是 TEXT 而非 `issue INTEGER` 的原因。

    一个 issue 和它开出的 PR 是**同一个 subject**（`issue:N`，靠分支名 `openagents/issue-N` 认亲）——它们的
    生命周期是一条线（issue → PR → merged），拆成两个 subject 只会让同-subject 串行失效（两个 agent 同时
    动一个 PR）。
    """
    subjects: list[str] = []
    for issue in github.list_issues(labels=[_LABEL_READY]):
        subjects.append(f"{_KIND_ISSUE}:{issue.number}")
    for pr in github.list_open_prs():
        branch = github.pr_head_branch(pr_number=pr.number)
        if branch.startswith(_BRANCH_PREFIX):
            continue  # 归属某个 issue subject（同一条生命周期），不另立门户
        subjects.append(f"{_KIND_PR}:{pr.number}")
    return subjects


def _intake(
    *,
    backend: Any,
    work_dir: Path,
    config: agent_config.AgentConfig,
    agent_id: str,
    now: datetime,
) -> None:
    """准入面（**唯一 agentic 的调度动作**）：新 issue 三态审 → 打 `ready` → curator 排依赖 → 落 `blocked_by`。

    对每个「无 `ready` label 的新 issue」（可攒一批）：
      1. **三态门控**——`skip` 直接准入 / `agent` 派 triager 判 actionable、过则准入 / `human` **在评论里
         跟人对话确认**、人点头才准入（见 `_ask_human`；`stages.triage` 是分诊的单一策略源）。
      2. **打 `ready` label**——准入令牌落 GitHub。
      3. **调 curator（T1）**——喂「当前所有 `ready` open issue 快照 + **已有依赖边（锚点）**」，出建议的
         `blocked_by` 边集。curator 是零逻辑 Template（agents/ 层约定）：只出结构化语义判断，不做调度、不落边。
      4. **validate**——本地用建议边重建内存 DAG，校验**无环** + 引用的都是真实 issue。
      5. **落边**——validate 过才为**新节点** `POST blocked_by`；**已有边（含人在 UI 手设的）作锚点不动**。
         失败则不落任何边 + 打 `needs-human`。

    **为什么排边要 LLM，而路由不要。** 依赖是**语义判断**——机械手段（文件重叠分析）只能捕「文件冲突序」，
    捕不到「逻辑序」（A 定义了接口、B 才能用，两者可能不碰同一文件）。而 `_classify` 的每个谓词都是从
    GitHub 读到的布尔/枚举：让 LLM 来判是拿不确定性换零收益，还引入一个致命失败模式——在一个红着的 PR 上
    幻觉出「全绿 → 合并」。**合并不可逆。**

    **为什么边落 GitHub 而不落本地。** 依赖边是**人机共写的可变真相**（人在 UI 手设、agent 走 API），本地
    第二份必然要对账。GitHub 原生 dependencies（2025-08 GA）给了专有命名空间 + 结构化读取 + webhook + UI。
    curator 因此只能**受锚增量**补边、不能全量覆盖（会抹掉人手设的边）——代价是它纠不了自己上一轮排错的
    既有边（见 spec Unresolved）。
    """
    github.ensure_label(name=_LABEL_READY, description="openagents 守夜：已过准入门控")
    owner = config.stages.owner_of(stage=agent_config.STAGE_TRIAGE)
    # Spec-0065/T2: 准入面的两个 agent 调用（triager / curator）跑在**生产者线程**上，同样要套硬超时。
    # 它们挂住的话，整条主循环就停在那里：不再有 tick、不再有 `_reclaim_dead`（真死掉的持有者永不被回收）、
    # `--once` 连排空都进不去——比某个 subject 卡住严重得多。这里没有认领的行，故不传 lock_fd。
    timed = _TimedBackend(inner=backend, timeout_seconds=_AGENT_TIMEOUT_SECONDS, lock_fd=None)
    admitted = 0
    # Spec-0035/T4: 发现段慢检查进度日志——拉带标签 issue 走网络，卡住时输出停在这行、一眼定位。
    _log(message="▶ 发现段：拉取带标签 issue…")
    for issue in github.list_issues(labels=config.labels):
        if _LABEL_READY in issue.labels or _LABEL_NEEDS_HUMAN in issue.labels:
            continue
        try:
            admitted += _admit(
                owner=owner,
                backend=timed,
                work_dir=Path(work_dir),
                issue=issue,
                agent_id=agent_id,
            )
        except Exception as exc:  # noqa: BLE001 —— 单 issue 准入失败不拖垮整轮（含 _ActTimeout）
            _log(message=f"✗ issue #{issue.number} 准入失败，跳过：{exc}")
    if admitted:
        _order_edges(backend=timed, work_dir=Path(work_dir), agent_id=agent_id)


def _admit(*, owner: str, backend: Any, work_dir: Path, issue: Any, agent_id: str) -> int:
    """单个新 issue 的三态准入：`skip` 直接放行 / `agent` 派 triager 判 / `human` **在评论里跟人对话确认**。

    返回准入数（0/1）。`human` 态是一场**跨 tick 的对话**，不是一次挂起——见 `_ask_human`。
    """

    def _on_agent() -> int:
        # Spec-0035/T4: 发现段慢检查进度日志——triager LLM 分诊耗时且过程全哑，卡住时输出停在这行。
        _log(message=f"… issue #{issue.number} 自检分诊方向(LLM)…")
        verdict = stages.triage(backend=backend, work_dir=work_dir, issue=issue)
        if verdict["actionable"]:
            return _grant_ready(issue=issue)
        _park_needs_human(
            subject=f"{_KIND_ISSUE}:{issue.number}",
            body=f"⏸ openagents 分诊：本 issue 暂不可直接派单，请对齐后再触发。\n\n{verdict['reason']}",
            agent_id=agent_id,
        )
        return 0

    return route(
        owner=owner,
        on_agent=_on_agent,
        on_human=lambda: _ask_human(
            backend=backend, work_dir=work_dir, issue=issue, agent_id=agent_id
        ),
        on_skip=lambda: _grant_ready(issue=issue),
    )


def _ask_human(*, backend: Any, work_dir: Path, issue: Any, agent_id: str) -> int:
    """`triage: human` 的准入：**在 issue 评论里跟人对话确认**，人点头才打 `ready`。返回准入数（0/1）。

    三个状态，全部从 GitHub 现态推出来（level-triggered，零本地记忆——重启/换机器都不影响）：

    1. **还没问**（评论流里没有 `_ADMIT_ASK_MARK`）→ 发一条签名提问评论，返回。**零 LLM**。
    2. **问了、人还没回话**（提问之后没有任何无签名评论）→ 什么都不做，返回。**零 LLM**——这是关键：
       准入面每 tick 都会重新扫到这个 issue（它没有 `ready` 也没有 `needs-human`），若每轮都叫一次
       agent，一个等着人回话的 issue 就成了一台按 tick 计费的印钞机。
    3. **人回话了** → 若人最新那句话已经判过（有更新的裁决戳）就沿用（**零 LLM**，见 `_admit_verdict`），
       否则把对话交 **admitter** 判 → 裁决先盖成一条签名评论、再落地：点头 → `_grant_ready`；没点头 →
       `_park_needs_human`（带 admitter 的理由）。

    **为什么不是「挂 `needs-human` 等人摘 label」。** 那是个死胡同：`needs-human` 在 `_classify` 里是
    TERMINAL，`_intake` 也会跳过带它的 issue —— 挂上去之后守夜就再也不看这个 issue 了，人回什么话都没人
    读，只能靠人手动摘 label。而 `human` 态的语义恰恰是「**这个决定得由人拍板**」，人拍板的自然方式是
    **说话**，不是去操作 label。

    **判「人点头没有」必须用 admitter，不能用 triager**（spec 原文写的是 replier，实现期两次改判）：
    - **replier 不行**——它的提示词是 **PR 语境**的（`$pr_number` / `$branch` / 「若需要改代码就改，
      commit+push」）：对着一个还没有 PR 的 issue 叫起来，等于叫它去改代码。
    - **triager 更不行，而且是危险的那种不行**——它判的是另一个问题（issue 正文内部有没有自相矛盾），
      且纪律是 **fail-open**（「拿不准就判可派单」）。人明说「先别做，这个方向我还没想清楚」并不属于它
      那五类矛盾中的任何一类 → 它会照判 `actionable=true` → **在人明确否决之下把活派出去**。那道人闸会
      当场退化成一台偏向「是」的 agent 闸——比原来那个死胡同更坏。
    - 故新增 `admitter`（`stages.admit`），判据就是「人到底点头没有」，纪律 **fail-closed**：看不懂、
      答非所问、路过说句话、拿不准 —— 一律当没点头。漏判只是多等一轮，误判是违背人的意愿开工。

    **谁算「人回话了」也必须在代码里判死，不能交给 agent。** 只认**我们提问之后**发的、**没有我方签名**
    的评论。少任何一个条件都会自触发：我方评论（park 理由、attempt 戳）若没签名就会被当成人的回话，
    agent 于是对着自己写的话开会——`identity` 那套签名纪律存在的全部意义就是堵这个（故 `_park_needs_human`
    也必须签名）。
    """
    subject = f"{_KIND_ISSUE}:{issue.number}"
    comments = github.list_issue_comments(number=issue.number)
    ask = _latest_marked(comments=comments, mark=_ADMIT_ASK_MARK)
    if ask is None:
        _post_admit_ask(issue=issue, agent_id=agent_id)
        return 0
    replies = _human_replies(comments=comments, ask=ask)
    if not replies:
        return 0  # 维护者还没回话 → 零 LLM 等着（下一 tick 再看）
    reply_key = _reply_key(reply=replies[-1])
    verdict = _admit_verdict(comments=comments, reply_key=reply_key)
    if verdict is None:  # 人这句话还没判过
        if _admit_tried(comments=comments, reply_key=reply_key):
            # 有 try 戳、却没有裁决戳 ⇒ 上一轮在 agent 那里判崩了（输出不是 JSON / 超时 / 429）。**零 LLM**
            # 转人工：一条人类回复只买一次 agent 调用，不然一个判不动的 issue 就是每 tick 一次的印钞机。
            _park_needs_human(
                subject=subject,
                body=(
                    "⏸ openagents 准入对话：上一轮的准入裁决**没能跑出结果**（agent 超时/输出不合约/"
                    "`gh` 抖动），为免每轮重烧一次 LLM，先停在这里。\n\n"
                    "想重来：**在下面再回一条评论**（哪怕只是把上一句重说一遍），然后摘掉本 label——"
                    "守夜按新的那句话重判一次。"
                ),
                agent_id=agent_id,
            )
            return 0
        # 花钱之前先盖戳（这一步就是 LLM 的准入券）：盖不上（`gh` 挂了）就抛在这里，**零 LLM**，下一 tick 重来。
        _post_admit_try(issue=issue, reply_key=reply_key, agent_id=agent_id)
        verdict = stages.admit(
            backend=backend,
            work_dir=work_dir,
            issue=issue,
            dialogue=_dialogue(comments=comments, ask=ask),
        )
        # 裁决**先落 GitHub 再落地**：打 label 那步若挂了（429/403），下一 tick 读回这条戳直接重试落地，
        # 不必再叫一次 agent。否则 `gh` 每失败一轮就重判一次——又一台按 tick 计费的印钞机。
        _post_admit_verdict(issue=issue, verdict=verdict, reply_key=reply_key, agent_id=agent_id)
    if verdict["approved"]:
        _log(message=f"✓ issue #{issue.number}：人已点头（准入对话）→ 准入")
        return _grant_ready(issue=issue)
    _park_needs_human(
        subject=subject,
        body=(
            "⏸ openagents 准入对话：没读到你的明确点头，先停在这里（准入闸 fail-closed——"
            "宁可多等你一句话，也不擅自开工）。\n\n"
            f"{verdict['reason']}\n\n"
            "想让它开工：**在下面回一条评论**说清楚，然后摘掉本 label——守夜会读你新说的这句话重判。"
            "（只摘 label、不说话的话，你上一句还是那句，裁决也还是这个。）"
        ),
        agent_id=agent_id,
    )
    return 0


def _post_admit_ask(*, issue: Any, agent_id: str) -> None:
    """发那条「请你拍板」的**签名**提问评论。签名是必须的：不签就会被下一轮当成人的回话（自问自答）。"""
    github.issue_comment(
        number=issue.number,
        body=identity.sign(
            body=(
                f"{_ADMIT_ASK_MARK}\n"
                "🙋 openagents 准入：本 issue 被分诊为 `triage: human` —— 派不派单**由你拍板**。\n\n"
                "请直接回话：说「可以」（或补齐你要的边界/取舍）我就打 `ready` 开始派单；说不行、"
                "或讲清还缺什么，我就挂 `needs-human` 停在这里等你。\n\n"
                "（拍板只认**本仓库维护者**（owner / member / collaborator）说的话——路人评论我会当噪声"
                "略过。在维护者回话之前，守夜不会对这个 issue 做任何事，也不会再问第二遍。）"
            ),
            agent_id=agent_id,
        ),
    )
    _log(message=f"🙋 issue #{issue.number}：`triage: human` → 已在评论里请人拍板，等回话")


def _post_admit_try(*, issue: Any, reply_key: str, agent_id: str) -> None:
    """**在叫 admitter 之前**盖的签名戳：「人这句话，我这就去判了」。这一步是 LLM 花费的准入券。

    它必须先于 `stages.admit` 落到 GitHub 上：agent 那边任何形式的判崩（输出不是 JSON、`_ActTimeout`、
    backend 429）都会把 `_ask_human` 整个抛掉，此时 issue 上既没有 `ready` 也没有 `needs-human`，下一 tick
    `_intake` 照样扫到它 —— 没有这个戳，那就是**每 tick 烧一次 LLM，直到人来关掉守夜**。有了它，一条人类
    回复至多买到一次 agent 调用；戳本身盖不上（`gh` 挂了）则当场抛出，**零 LLM**，下一 tick 原样重来。
    """
    github.issue_comment(
        number=issue.number,
        body=identity.sign(
            body=(
                f"{_ADMIT_TRY_MARK}{reply_key} -->\n"
                "⏳ openagents 准入：读到你的回话了，正在判定是否点头。"
            ),
            agent_id=agent_id,
        ),
    )


def _post_admit_verdict(*, issue: Any, verdict: dict, reply_key: str, agent_id: str) -> None:
    """把准入裁决盖成一条**签名**评论——「人这句话已经判过了」的唯一持久痕迹（读 GitHub 现态，零本地记忆）。"""
    flag = _ADMIT_APPROVED if verdict["approved"] else _ADMIT_REFUSED
    github.issue_comment(
        number=issue.number,
        body=identity.sign(
            body=(
                f"{_ADMIT_VERDICT_MARK}{flag}:{reply_key} -->\n"
                f"{'✓ 读到你的点头' if verdict['approved'] else '⏸ 没读到明确的点头'}："
                f"{verdict['reason']}"
            ),
            agent_id=agent_id,
        ),
    )


def _reply_key(*, reply: github.Comment) -> str:
    """人那句话的身份：GitHub comment id（node id，永不复用）。id 读不到时退回 created_at 兜底。"""
    return reply.id or reply.created_at


def _is_our_stamp(*, comment: github.Comment) -> bool:
    """这条评论算不算**我们盖的**准入戳（裁决 / try）——判据落在**外人伪造不了的那一位**上。

    准入戳的标记串（`_ADMIT_VERDICT_MARK` 等）是公开的 HTML 注释，签名 `<!-- openagents:agent=… -->`
    同样是**公开可抄的文本**——「有标记」「有签名」两条都挡不住伪造：公开仓库里任何路人都能贴一条
    `<!-- openagents:admit-verdict:approved:<那人的评论 id> -->` + `<!-- openagents:agent=x -->`，
    `_admit_verdict` 一读就当成「上一轮已判过、approved」→ **零 LLM 直接放行**，绕过维护者闸和 admitter
    （`_human_replies` 认「谁在回话」时查了 `authorAssociation`，可这两个**读戳**的地方一处都没查——正是这道
    非对称给了攻击面）。唯一伪造不了的是 `authorAssociation`：它由 GitHub 按**真实作者**算出、不进评论
    正文、路人写不进去。故戳只在「维护者关联 **且** 带我方签名」两者俱全时才认——我们的 bot 恰是以维护者
    身份（能打 label / 推分支 / 合并的账号必是 OWNER/MEMBER/COLLABORATOR）盖下这些戳的，NONE / CONTRIBUTOR
    的路人伪造多少标记都过不了这一关。fail-closed：关联读不到（空串）一律不认。
    """
    return (
        comment.author_association in _MAINTAINER_ASSOCIATIONS
        and identity.parse_agent_id(body=comment.body) is not None
    )


def _admit_verdict(*, comments: list[github.Comment], reply_key: str) -> dict | None:
    """读回**针对人这句话**的裁决戳（没有 → None，即这句话还没判过）。省掉一次重复的 agent 调用。

    戳挂在**人那条评论的 id** 上，判据是精确相等，不是时间先后。两层意思：

    - **人还能改主意**：refused 之后我们挂 `needs-human`（TERMINAL，`_intake` 跳过），人按提示回一句
      「行，做吧」再摘掉 label —— 新话是一条新评论、新 id，旧裁决自动作废、重判。若戳挂在「我们的提问」
      上，那条 refused 会一直命中、把新说的话彻底盖住，**人再也无法点头**。
    - **不能拿时间戳当身份**：GitHub 的 createdAt 只到秒。`stamp.created_at >= reply.created_at` 在同秒时
      恒成立 → 人新回的那句话被旧 refused 戳吞掉，又回到「永久拒绝」；换成 `>` 则我们自己盖的戳判不了
      自己判过的那句话 → 每 tick 重判。id 是身份不是刻度，换一句话就换一个 id，两头都不漏。

    人不开口（只摘 label，或 `gh` 抖动导致上一轮 label 没打上）→ 沿用旧裁决，**零 LLM**。
    """
    for comment in comments:
        if not _is_our_stamp(
            comment=comment
        ):  # 伪造的戳（路人抄标记+签名）不算数——见 `_is_our_stamp`
            continue
        if f"{_ADMIT_VERDICT_MARK}{_ADMIT_APPROVED}:{reply_key} -->" in comment.body:
            return {"approved": True, "reason": "（沿用上一轮已盖的准入裁决）"}
        if f"{_ADMIT_VERDICT_MARK}{_ADMIT_REFUSED}:{reply_key} -->" in comment.body:
            return {"approved": False, "reason": "（沿用上一轮已盖的准入裁决）"}
    return None


def _admit_tried(*, comments: list[github.Comment], reply_key: str) -> bool:
    """人这句话是不是已经烧过一次 agent（有 try 戳）。有 try 无裁决 ⇒ 上一轮判崩了 ⇒ 零 LLM 转人工。"""
    return any(
        _is_our_stamp(comment=comment)  # 伪造的 try 戳（路人强推 park）不算数——见 `_is_our_stamp`
        and f"{_ADMIT_TRY_MARK}{reply_key} -->" in comment.body
        for comment in comments
    )


def _human_replies(*, comments: list[github.Comment], ask: github.Comment) -> list[github.Comment]:
    """「**人**回话了」的判据（**代码里判死，不交给 agent**）。三个条件，缺一不可：

    1. **发在我们提问之后**——少了它，提问前的旧评论会被当成回话，issue 一进 human 态就自动放行。
    2. **没有我方签名**——少了它，我们自己发的评论（park 理由、try 戳、裁决戳）会被当成人的回话，agent
       对着自己写的话开会（`identity` 签名纪律要堵的正是这个自问自答死循环）。
    3. **说话的人是维护者**（`authorAssociation` ∈ OWNER/MEMBER/COLLABORATOR）——少了它，这道闸**谁都不
       认**：公开仓库里任何一个路人回一句「可以，做吧」就能把活派出去。admitter 的提示词拦不住这个——
       它读到的只是一段文本，压根不知道「该听谁的」；而这段文本恰恰是**外人可写**的。fail-closed：关系
       读不到（空串）、或只是 CONTRIBUTOR / NONE ⇒ 不算拍板，当噪声略过。
    """
    return sorted(
        (
            comment
            for comment in comments
            if comment.created_at > ask.created_at
            and identity.parse_agent_id(body=comment.body) is None
            and comment.author_association in _MAINTAINER_ASSOCIATIONS
        ),
        key=lambda comment: comment.created_at,  # 排序，好让调用方取 [-1] 拿到「人最新那句话」
    )


def _dialogue(*, comments: list[github.Comment], ask: github.Comment) -> str:
    """交给 admitter 的对话逐字稿：**我们问的那句 + 维护者的回话**（按时间序，标明谁说的）。

    只放这两类，别的一律不进 prompt。路人评论、我们自己的 try/裁决/park 戳都被挡在外面：前者是外人可写
    的文本，混进来等于把一道 fail-closed 的人闸暴露给提示词注入；后者会让 agent 读到自己上一轮的话，
    在同一段对话里跟自己开会。判据是「谁说的」（`_human_replies` 已判死），不是「说了什么」。
    """
    turns = [ask, *_human_replies(comments=comments, ask=ask)]
    return "\n\n".join(
        f"- **{'openagents（我方提问）' if identity.parse_agent_id(body=t.body) else t.author}**："
        f"{t.body.strip()}"
        for t in turns
    )


def _latest_marked(*, comments: list[github.Comment], mark: str) -> github.Comment | None:
    """带某个标记的最新一条评论（无 → None）。标记是「这件事做过没有」的唯一真相，读 GitHub 现态。"""
    marked = [comment for comment in comments if mark in comment.body]
    if not marked:
        return None
    return max(marked, key=lambda comment: comment.created_at)


def _grant_ready(*, issue: Any) -> int:
    """准入令牌落 GitHub：打 `ready` label（幂等）。返回 1（供 `_intake` 计准入数）。"""
    github.issue_add_label(number=issue.number, name=_LABEL_READY)
    _log(message=f"✓ issue #{issue.number}：过准入门控，已打 {_LABEL_READY}")
    return 1


def _order_edges(*, backend: Any, work_dir: Path, agent_id: str) -> None:
    """调 curator（T1）排依赖 → validate（无环 + 真实 issue）→ 只为**新节点** POST `blocked_by`（受锚增量）。

    已有边（含人在 UI 手设的）**原样带进 prompt 作锚点、只读不改**——整张覆盖会抹掉人的改动。validate 不过
    （成环 / 引用了不存在的 issue）→ **不落任何边** + 把涉事 issue 打 `needs-human` 交人（宁可停，也不要把
    一个错的依赖图写进 GitHub：错边会凭空冻住本可并行的流转，而且是持久的）。
    """
    ready = github.list_issues(labels=[_LABEL_READY])
    if len(ready) < 2:
        return  # 少于两个节点，无边可排
    known = {issue.number for issue in ready}
    existing = {issue.number: _blocker_numbers(number=issue.number) for issue in ready}

    snapshot = "\n".join(f"- #{issue.number}「{issue.title}」：{issue.body}" for issue in ready)
    anchors = json.dumps(
        [
            {"issue": number, "blocked_by": blockers}
            for number, blockers in sorted(existing.items())
            if blockers
        ],
        ensure_ascii=False,
    )
    payload = engine.run_agent(
        curator,
        backend=backend,
        work_dir=Path(work_dir),
        context=snapshot,
        issue_snapshot=snapshot,
        existing_edges=anchors,
    )
    proposed = _proposed_edges(
        edges=payload["edges"], known=known, existing=existing, agent_id=agent_id
    )
    if proposed is None:
        return
    for issue_number, blocker in proposed:
        github.add_blocked_by(number=issue_number, blocker_number=blocker)
        _log(message=f"⇢ 依赖边：#{issue_number} blocked_by #{blocker}")


def _blocker_numbers(*, number: int) -> list[int]:
    """一个 issue 当前的 `blocked_by` 对端编号（锚点，只读）。"""
    return [blocker.number for blocker in github.list_blocked_by(number=number)]


def _proposed_edges(
    *, edges: list, known: set[int], existing: dict[int, list[int]], agent_id: str
) -> list[tuple[int, int]] | None:
    """校验 curator 的建议边 → 该落的**新**边列表；validate 不过 → `None`（不落任何边 + park 涉事 issue）。

    三道校验，全是本地纯计算（不信 agent 自述）：**引用的都是真实 ready issue**（防幻觉出不存在的编号）、
    **不自指**、**并入已有边后仍无环**（Kahn 拓扑排序）。有一条不过就整批否决——半张错图比没有图更糟。
    只返回**新增**边（已有边作锚点不动，也不重复 POST）。
    """
    graph = {number: set(blockers) for number, blockers in existing.items()}
    fresh: list[tuple[int, int]] = []
    bad: set[int] = set()
    hallucinated = False  # 引用了根本不存在的编号：park 不到具体 issue 头上，只能整批否决 + 记日志
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        issue_number = edge.get("issue")
        blockers = edge.get("blocked_by") or []
        if issue_number not in known or not isinstance(blockers, list):
            # **绝不 `bad.add(0)`**：0 不是任何 issue 的编号，park 它会往 issue **#0** 上写 label/评论
            # （幻觉编号 → 打扰一个无关的、甚至不存在的对象）。整批照样否决，只是不冤枉任何一个 issue。
            if isinstance(issue_number, int) and issue_number in known:
                bad.add(issue_number)
            else:
                hallucinated = True
            continue
        for blocker in blockers:
            if blocker not in known or blocker == issue_number:
                bad.add(issue_number)
                continue
            graph.setdefault(issue_number, set()).add(blocker)
            if blocker not in existing.get(issue_number, []):
                fresh.append((issue_number, blocker))
    cyclic = _cycle_members(graph=graph)
    if bad or cyclic or hallucinated:
        # **只 park 涉事的 issue**（坏边的宿主 + 环上的成员），不是整个 ready 集。一条坏边就把所有 ready
        # issue 全打成 needs-human，等于让 curator 的一次幻觉冻结整条流水线——爆炸半径必须收敛到当事者。
        for number in sorted(bad | cyclic):
            _park_needs_human(
                subject=f"{_KIND_ISSUE}:{number}",
                body=(
                    "⏸ openagents 守夜：curator 排出的依赖图未过校验"
                    "（成环 / 引用了不存在的 issue），本轮**未落任何边**，交人确认。"
                ),
                agent_id=agent_id,
            )
        _log(message="✗ curator 依赖图未过校验（成环 / 幻觉编号），本轮不落任何边")
        return None
    return fresh


def _cycle_members(*, graph: dict[int, set[int]]) -> set[int]:
    """Kahn 拓扑排序：剥不掉的节点**就是**环上（及被环卡住）的那些。无环 → 空集。纯函数。

    返回**成员**而不只是一个 bool，是为了让 park 的爆炸半径收敛到当事者：一条 A↔B 的坏边只该冻结 A 和 B，
    不该把整个 ready 集打成 needs-human（见 `_proposed_edges`）。
    """
    pending = {node: set(blockers) for node, blockers in graph.items()}
    for blockers in graph.values():
        for blocker in blockers:
            pending.setdefault(blocker, set())
    while True:
        free = [node for node, blockers in pending.items() if not blockers]
        if not free:
            return set(pending)
        for node in free:
            pending.pop(node)
        for blockers in pending.values():
            blockers.difference_update(free)


def _has_cycle(*, graph: dict[int, set[int]]) -> bool:
    """图里有没有环（`_cycle_members` 的 bool 视图）。纯函数。"""
    return bool(_cycle_members(graph=graph))


def route(
    *,
    owner: str,
    on_agent: Callable[[], Any],
    on_human: Callable[[], Any],
    on_skip: Callable[[], Any],
) -> Any:
    """三态策略路由：owner=agent→on_agent() / human→on_human() / skip→on_skip()。编排点的唯一分支源。

    高阶函数——各闸把「自动化怎么做 / 停等人怎么做 / 跳过怎么做」以三个零参 thunk 传入，本函数只据 config
    的 owner 选一个执行（承旧串行 vigil 的 route）。注意 `_sense` 已把 `skip` 归一成「事实上已过闸」，故
    `_act` 里的可配闸只会看到 agent / human 两态——`on_skip` 仍保留是为了 `_intake` 的 `triage: skip`。
    """
    if owner == _AGENT:
        return on_agent()
    if owner == _HUMAN:
        return on_human()
    return on_skip()


def _park(*, facts: _Facts, verdict: _Verdict, clock: _Clock, now: datetime, agent_id: str) -> None:
    """看门狗的收尾动作：给 subject 打 `needs-human` + 贴一条**机械诊断**评论（**不叫 LLM**）。

    诊断按 `verdict.reason` 组装成因假设，例如 `awaiting-ci`：「head `abc123` 推送 43 分钟仍无任何 check：
    base 不是 main？Actions 被禁？workflow 未匹配？」——这些是可枚举的机械假设，不需要模型来猜。

    `needs-human` 是 TERMINAL → **轮询停止**。人摘掉 label，`_classify` 自动重新活过来——这是 level-triggered
    白送的自愈（无历史 → 无需清理任何本地残留状态）。park 完全可逆，这也是敢把阈值设宽的前提。

    注意 agent **也能主动**打 `needs-human`（它一眼看出要人来定，不用干等超时）——那是**主路径**；看门狗是
    **兜底**（防它忘了、判错了、或根本没被叫起）。
    """
    age = (
        int((now - clock.last_progress_at).total_seconds())
        if clock.last_progress_at is not None
        else -1
    )
    _park_needs_human(
        subject=facts.subject,
        body=(
            f"⏸ openagents 守夜看门狗：`{facts.subject}` 卡在 **{verdict.reason or verdict.kind}** "
            f"已 {age}s（head `{_short(sha=facts.head_sha) or '—'}`）。\n\n"
            f"{_diagnosis(reason=verdict.reason or verdict.kind)}\n\n"
            "这是机械诊断（未叫 agent）。处理后摘掉本 label，守夜会自动重新接管。"
        ),
        agent_id=agent_id,
    )


def _diagnosis(*, reason: str) -> str:
    """按 QUIET 成因给可枚举的**机械**假设（不叫模型猜）。未知成因 → 通用兜底文案。"""
    return {
        _AWAITING_CI: (
            "可能成因：base 不是 main？Actions 被禁？workflow 的 `on:` 未匹配本分支？"
            "PR 处于 draft 且 workflow 排除了 draft？"
        ),
        _AWAITING_MERGEABILITY: "GitHub 迟迟算不出 merge ref：分支被删？base 分支不存在？仓库正在迁移？",
        _AWAITING_EFFECT: (
            "agent 已出手但**状态一个字节没变**（fp 未变）：它可能以为自己修了（rerun 了 CI 但没触发、"
            "改了个无关文件）。见上方它自己盖的 attempt 戳评论里的结论。"
        ),
        _AWAITING_BLOCKERS: "上游 blocker 迟迟未合：依赖图排错了？成环？上游自己也卡住了？",
        _IN_FLIGHT: (
            "认领已超 IN_FLIGHT 告警阈值：持有者进程还活着（flock 未释放），但可能挂死在一个不返回的调用上。"
            "**队列行未被回收**（回收活着的持有者 = 双跑）。"
        ),
    }.get(reason, "未知成因，请人工查看。")


def _priority_default(*, verdict: _Verdict) -> int:
    """缺省优先级：**先收尾在制品，再开新工**。返回 `work_queue.priority` 的整数（越大越先）。

        reply(6) > merge(5) > review-or-fix(4) > e2e(3) > fix-ci(2) ≈ rebase(2) > solve(1)
          ↑                                                                        ↑
        人在等                                                            开新工，排最后

    一个近乎合完的 PR 正占着一条依赖链的下游；开一个新 issue 只是增加在制品。`ORDER BY priority DESC` 在
    **领取时**求值，故久候行的优先级不冻结在入队时刻。权重可插拔（`run_vigil(priority_fn=…)`），是否加入
    aging 因子见 spec Unresolved。
    """
    return _PRIORITY_DEFAULTS.get(verdict.action or "", 0)


def _hang(*, quiet_counts: dict[str, int], in_flight_count: int, interval: int) -> None:
    """本 tick 入队 0（无人可动）→ 打一条可观测提示，区分成因，再由主循环 sleep。

    按 QUIET 成因聚合（「3 个在等 CI、1 个在等上游合并、2 个已出手待生效」）+ 在飞数——「什么都没发生」的
    原因必须能一眼看出，否则「全都健康地在等」和「全都卡死了」在日志里长得一模一样。

    **成环优雅落此**：curator 误排 A↔B → 两者恒 `QUIET(awaiting-blockers)` → 每 tick 都被这里提示，**不静默
    卡死**。worker 侧此时自然阻塞在空表轮询上，不忙等。
    """
    parts = [f"{count} 个 {reason}" for reason, count in sorted(quiet_counts.items()) if count]
    if in_flight_count:
        parts.insert(0, f"{in_flight_count} 个在飞")
    detail = "、".join(parts) if parts else "前沿空（无 ready issue、无 open PR）"
    _log(message=f"… 本轮无人可动：{detail}；{interval}s 后再扫一轮")


# --------------------------------------------------------------------------------------------------
# 消费者（K 个 worker）：claim 一个 subject（+ flock）→ reconcile 推进到卡住为止 → done / requeue-or-park。
# --------------------------------------------------------------------------------------------------


def _worker_loop(
    *,
    db_path: Path,
    backend: Any,
    state: RuntimeState,
    work_dir: Path,
    config: agent_config.AgentConfig,
    agent_id: str,
    now_fn: Callable[[], datetime],
    stop_event: threading.Event,
    worker_id: str,
) -> None:
    """消费者常驻循环：`_claim_next` 原子领一个 subject（+ 持 flock）→ `_reconcile` → `_mark_done`（先删行后
    释锁）→ 立刻再领（**无批屏障**）。

        while not stop_event.is_set():
            claimed = _claim_next(...)                               # (row, fd)
            if claimed is None:
                stop_event.wait(_WORKER_POLL_SECONDS); continue      # 空表：拉式兜底，停机时立即醒
            row, fd = claimed
            try:
                _reconcile(subject=row["subject"], ...)              # 推进到卡住为止（全程持锁）
                _mark_done(task_id=row["id"], fd=fd)                 # 先删行，后 close(fd)
            except Exception:                                        # 含 _act 硬超时
                _requeue_or_park(task_id=row["id"], subject=row["subject"], fd=fd, ...)

    单 subject 异常**就地隔离**（记日志、不上抛）——一个 subject 崩不该杀 worker 线程、缩小整个并发池。
    领取时的 `subject UNIQUE` 已保证这个 worker 独占该 subject（别的 worker 领不到同一行），故 subject 内无需
    再加任何锁。每 worker 一条私有 `_connect`（sqlite3 连接不跨线程共享）。`now_fn` 每次领时现取。

    **收尾（`_claim_next` / `_mark_done` / `_requeue_or_park`）也必须在 try 里。** 它们会碰 sqlite，而 sqlite
    会抛（`database is locked`：生产者 + K 个 worker 抢写锁，`busy_timeout` 到点就抛）。这三处任一裸抛都会
    **静默杀死 worker 线程**：并发池悄悄缩水，且若死在 `_mark_done` 的 `DELETE` 与 `close(fd)` 之间，那行
    `claimed` 会**永远**留着——fd 还在本进程手里、flock 没释放，`_reclaim_dead` 判它「持有者活着」，于是永不
    回收、也永不重入队（`INSERT OR IGNORE` 撞 UNIQUE 成 no-op），该 subject 就此死掉。故：

      - `_ActTimeout`（agent 挂死）→ **park 交人，不回队**：见 `_TimedBackend`（杀干净只是尽力而为，把可能
        还活着的 agent 的活重新发出去 = 双跑）。
      - 其它异常 → 回队重试（`attempts` 到顶自动 park）。
      - 收尾自身再抛 → `_release`（下面）兜底：**保证 close(fd)**。锁一放，这行最坏也只是被 `_reclaim_dead`
        当「持有者已死」回收回 queued——重跑一遍是幂等的（level-triggered），而孤儿行是永久的。
    """
    conn = _connect(db_path=db_path)
    try:
        while not stop_event.is_set():
            try:
                claimed = _claim_next(
                    conn=conn, work_dir=Path(work_dir), worker_id=worker_id, now=now_fn()
                )
            except Exception as exc:  # noqa: BLE001 —— 领取失败（sqlite 抖动）不该杀 worker
                _log(message=f"✗ {worker_id}：领取失败，下一轮再试：{exc}")
                stop_event.wait(_WORKER_POLL_SECONDS)
                continue
            if claimed is None:
                stop_event.wait(_WORKER_POLL_SECONDS)
                continue
            row, fd = claimed
            _run_claimed(
                conn=conn,
                row=row,
                fd=fd,
                backend=backend,
                state=state,
                work_dir=Path(work_dir),
                config=config,
                agent_id=agent_id,
                now_fn=now_fn,
            )
    finally:
        conn.close()


def _run_claimed(
    *,
    conn: sqlite3.Connection,
    row: dict,
    fd: int,
    backend: Any,
    state: RuntimeState,
    work_dir: Path,
    config: agent_config.AgentConfig,
    agent_id: str,
    now_fn: Callable[[], datetime],
) -> None:
    """一次认领的全生命周期：reconcile → 收工 / 回队 / park，**任何路径都不上抛、且必定 close(fd)**。

    从 `_worker_loop` 里切出来，只为让「异常一律不越过这一层」这条不变式有一个显式的、可单测的边界（worker
    线程的存活是整个并发池的地基——它不能因为某个 subject 或某次 sqlite 抖动而少一条）。

    **进门先查上限，再谈动手。** `attempts` 在**领取时**累加，超顶的行有两种来路，两种都不该再叫 agent：
    - 上一轮已判 park，但 park 的 `gh` 抛了（限流/掉网）→ 行留在 `claimed` 被 `_reclaim_dead` 正常回收。
      **要重试的是那次 park，不是那次 agent 调用**：不拦的话 `gh` 持续失败就是一个无限烧 LLM 的环；在超时 park
      那条路上更糟——被强杀的 agent 是否已经推了东西无法证明，重发一次正是那条 label 里写着「未自动重试」要
      避免的双跑。
    - 反复被领取却从未收工（agent 崩、守夜被 OOM/重启打死、worker 线程随进程一起没了）→ `_reclaim_dead` 每次
      把它打回队列、每次领取又 +1。这正是 `_MAX_ATTEMPTS` 存在的理由：它是**唯一**能发现「没能收工」的机制
      （那种死法在 GitHub 上零痕迹，fp 判不出、age 也判不出）。

    故这里**不假设**是哪一种。早先的版本一口咬定是前者并把它写进了 label——那是句会骗人的话：一个从没失败过、
    只是撞上几次守夜重启的健康 subject 也会走到这里。理由只陈述能证的事实：领了 N 次，一次都没收工。
    """
    subject = row["subject"]
    if int(row["attempts"]) > _MAX_ATTEMPTS:
        _log(message=f"⏸ {subject}：第 {row['attempts']} 次领取仍未收工 → 不再叫 agent，直接交人")
        _finish(
            conn=conn,
            task_id=row["id"],
            fd=fd,
            park=True,
            subject=subject,
            reason=(
                f"这一行被领取了 {row['attempts']} 次却一次都没能收工（上限 {_MAX_ATTEMPTS}）。"
                "成因可能是 agent 反复崩、守夜进程被反复重启，或上一轮已判交人但 `gh` 没发出去"
            ),
            agent_id=agent_id,
        )
        return
    try:
        _reconcile(
            backend=backend,
            state=state,
            work_dir=Path(work_dir),
            config=config,
            subject=subject,
            agent_id=agent_id,
            now_fn=now_fn,
            lock_fd=fd,  # Spec-0065/T2: 传给 agent 子进程继承——存活证明要跟着真正在干活的进程走
        )
    except _ActTimeout as exc:
        _log(message=f"⏱ {subject}：agent 挂死（{exc}），不回队、直接交人")
        _finish(
            conn=conn,
            task_id=row["id"],
            fd=fd,
            park=True,
            subject=subject,
            reason=f"agent 调用挂死并被强杀（{exc}）",
            agent_id=agent_id,
        )
        return
    except Exception as exc:  # noqa: BLE001 —— 单 subject 崩不该杀整条 worker
        _log(message=f"✗ {subject}：认领内失败：{exc}")
        _finish(
            conn=conn,
            task_id=row["id"],
            fd=fd,
            park=False,
            subject=subject,
            reason=str(exc),
            agent_id=agent_id,
        )
        return
    _finish(
        conn=conn,
        task_id=row["id"],
        fd=fd,
        park=None,
        subject=subject,
        reason="",
        agent_id=agent_id,
    )


def _finish(
    *,
    conn: sqlite3.Connection,
    task_id: int,
    fd: int,
    park: bool | None,
    subject: str,
    reason: str,
    agent_id: str,
) -> None:
    """收尾的**唯一出口**，保证 `close(fd)`：`park=None` 收工 / `False` 回队或到顶 park / `True` 直接 park。

    收尾里的 sqlite / GitHub 调用都可能抛（锁竞争、网络）。抛了也不上抛，只记日志——但 flock **一定**要还给
    内核：留着锁 = 一行 `claimed` 永远回收不了（见 `_worker_loop` 的说明）；放掉锁最坏是被 `_reclaim_dead`
    回收重跑，而重跑在 level-triggered 下是幂等的。**先写行、后释锁**的顺序在各分支里保持。

    **fd 恰好 close 一次。** 委托出去的两条路（`_mark_done` / `_requeue_or_park`）各自用 `finally` 兜住 close，
    所有权随调用移交 —— 故这里一进那两个分支就把 `closed` 置上，`finally` 的兜底**不再**碰它。多关一次不是无害
    的：fd 号会被别的线程复用（另一个 worker 的 claims 锁 / 一个 sqlite 句柄），关掉 = 放掉**别人**的 flock，
    那个还在跑的 worker 于是被判死、行被回收重领 → 双跑。兜底只覆盖 `park is True` 里 close 之前就抛的情形。
    """
    closed = False
    try:
        if park is True:
            _park_needs_human(  # 先落地交人：`gh` 抛了就让行留在 claimed（回收兜底），绝不静默重新派发
                subject=subject,
                body=(
                    f"⏸ openagents 守夜：`{subject}` 已交人。\n\n原因：{reason}\n\n"
                    "**未自动重试**——上一次 agent 调用是否已经改了/推了东西无法证明，重发一次可能双跑。"
                    "请人确认现场后摘掉本 label，守夜会自动重新接管。"
                ),
                agent_id=agent_id,
            )
            conn.execute("DELETE FROM work_queue WHERE id=?", (task_id,))  # 自动提交（见 _connect）
            closed = (
                True  # 先置位再 close：close 自己抛（EBADF）时 finally 不许再关一次同一个 fd 号
            )
            os.close(fd)
            return
        if park is False:
            closed = True  # fd 的所有权移交（它的 finally 保证 close 一次）——这里不再兜底重关
            _requeue_or_park(conn=conn, task_id=task_id, subject=subject, fd=fd, agent_id=agent_id)
            return
        closed = True  # 同上：所有权移交给 _mark_done
        _mark_done(conn=conn, task_id=task_id, fd=fd)
    except Exception as exc:  # noqa: BLE001 —— 收尾失败也不许杀 worker
        _log(message=f"✗ {subject}：收尾失败（行可能留在 claimed，将由回收兜底）：{exc}")
    finally:
        if not closed:
            _close_quietly(fd=fd)


def _close_quietly(*, fd: int) -> None:
    """兜底释放 flock（已关过 → 忽略）。锁必须还给内核，否则那行 `claimed` 永远判不了死。"""
    try:
        os.close(fd)
    except OSError:
        pass


def _reconcile(
    *,
    backend: Any,
    state: RuntimeState,
    work_dir: Path,
    config: agent_config.AgentConfig,
    subject: str,
    agent_id: str,
    now_fn: Callable[[], datetime],
    lock_fd: int | None,
) -> None:
    """领到一个 subject 之后：**循环推进到卡住为止**（不是「一 tick 推一步」）。

        last_fp = None
        while True:
            observed = _sense(subject)
            fp       = _fingerprint(observed.facts)
            verdict  = _classify(observed.facts, in_flight=False)   # 我就是那个 in-flight

            if verdict.kind is not _ACTIONABLE:      # 卡在外部（QUIET）或到终点（TERMINAL）
                return                               # 交还 slot，下一 tick 由生产者重新判定

            if fp == last_fp:                        # 我刚在这个状态上出过手，它没动 → 零进展
                _post_attempt_stamp(subject, fp, conclusion)     # 护栏一：盖戳，别再被叫起
                return

            last_fp = fp
            _act(observed, verdict)

    **为什么推进到卡住、而非推一步**：一个 CI 绿、e2e 齐、review 已过的 PR 应该在**一次认领**里走完⑨⑩⑪合掉，
    而不是烧掉三个 tick（每 tick 只走一支）。停止条件全是纯函数判断，不需要任何计数器。

    **正常的「干不动」不从这里收口，从 `needs-human` 收口。** agent 在 `_act` 里判断没辙 → 自己打 label +
    留理由 → 下一圈 `_sense` 读到 → 分支① TERMINAL → 上面第一个 `return`。**这是主路径。**

    **`fp == last_fp` 是兜底**，专防 agent **没意识到自己在空转**的那一类：它以为自己干了活（rerun 了 CI 但
    没触发、改了个无关文件、发了条「等 CI 重跑就好」的评论然后收工），所以不会去打 `needs-human`；而它每轮
    留的评论还会刷新 `last_progress_at`，**看门狗也永远不响**——除了机械比对 fp，没有任何东西拦得住它无限
    重跑。故此处盖 attempt 戳收工，生产者下一 tick 见到同 fp 的戳就不再入队。（盖戳本身不改 fp——`_Facts`
    不含 comment id，见 `_fingerprint`。）

    若 agent 其实推动了、只是 GitHub 还没反映出来（异步生效），下一 tick 的 fp 会与这枚（已陈旧的）戳不匹配
    → 正常重新入队 → **race 自愈**。

    **`in_flight` 恒传 `False`**：worker 自己就是那个 in-flight 的持有者（传 True 会让它立刻收工、空转）。
    持锁的 fd 由 `_worker_loop` 持有、覆盖本函数全程（见 `_claim_next` / `_reclaim_dead`）。
    """
    last_fp: str | None = None
    last_summary = ""
    for round_index in range(_MAX_RECONCILE_ROUNDS):
        observed = _sense(config=config, subject=subject)
        fp = _fingerprint(facts=observed.facts)
        verdict = _classify(facts=observed.facts, in_flight=False)  # 我就是那个 in-flight

        if verdict.kind != _ACTIONABLE:
            _log(message=f"⏹ {subject}：{verdict.kind}（{verdict.reason or '—'}），交还 slot")
            return

        if fp == last_fp:  # 零进展：我刚在这个状态上出过手，它一个字节没动
            _post_attempt_stamp(
                facts=observed.facts, fp=fp, conclusion=last_summary, agent_id=agent_id
            )
            return

        last_fp = fp
        # Spec-0066/T2: worker 旁路盖**活动段**阶段戳——此处 verdict 恒 ACTIONABLE（非 ACTIONABLE 已在上方
        # 交还 slot），`_phase_of` 取其 `action`，把生产者视角的泛 in-flight 解析成 solve/fix-ci/review-or-fix
        # 等真动作。旁路容错、不改控制流/fp。
        _record_timing(
            work_dir=Path(work_dir),
            subject=subject,
            facts=observed.facts,
            verdict=verdict,
            now=now_fn(),
        )
        last_summary = _act(
            backend=backend,
            state=state,
            work_dir=Path(work_dir),
            config=config,
            observed=observed,
            verdict=verdict,
            agent_id=agent_id,
            now=now_fn(),
            lock_fd=lock_fd,
        )
        _log(message=f"↻ {subject}：第 {round_index + 1}/{_MAX_RECONCILE_ROUNDS} 轮推进完成")

    # 轮数到顶仍 ACTIONABLE：不是「卡在外部」（那会 QUIET 交还 slot），也不是「零进展」（那 fp 会重复）——
    # 是**振荡**：每轮都真的改了 GitHub（fp 每轮都变），却在两三个状态间兜圈子。这是护栏一识别不了的死法
    # （它只记得上一轮的 fp），且每一圈都在烧 LLM。交人。
    _park_needs_human(
        subject=subject,
        body=(
            f"⏸ openagents 守夜：`{subject}` 在一次认领内连推 {_MAX_RECONCILE_ROUNDS} 轮仍未收敛"
            "（每轮都改了状态、却没走到终态——典型是 review 与 implement 互相打回的振荡）。\n\n"
            "已停止自动推进以免空烧模型调用。请人看一眼卡在哪，处理后摘掉本 label，守夜会自动重新接管。"
        ),
        agent_id=agent_id,
    )


def _act(
    *,
    backend: Any,
    state: RuntimeState,
    work_dir: Path,
    config: agent_config.AgentConfig,
    observed: _Observed,
    verdict: _Verdict,
    agent_id: str,
    now: datetime,
    lock_fd: int | None,
) -> str:
    """按 `verdict.action` 分派一个动作，返回 agent 的结论（供零进展时盖进 attempt 戳）。

    **路由永远是机械的；agent 只在动作内部干活。**

      - `solve` → 竖切：建隔离 worktree → rfc → 开 draft PR → implement → deliver（**不在此阻塞等 CI**——
        回到 `_reconcile` 的循环，下一圈 `_classify` 自会判成 `QUIET(awaiting-ci)` 并交还 slot）。
      - `rebase` → 先试机械 `update_branch`（无冲突时够用、零 LLM），不行再下放 agent 解冲突（git 交付与
        冲突自愈下放 agent：`force-with-lease`、仅本分支、禁裸 force）。
      - `fix-ci` → 读**当前 head** 的失败 check → 派 implementer 修 → push。
      - `e2e` → 跑 e2e（tester）、贴带 head_sha 溯源戳的证据评论。
      - `review-or-fix` → 出裁决 → 打 `review-approved:<sha7>` / `review-changes-requested:<sha7>`（sha 取
        **裁决所针对的那个 head**）/ 按 CHANGES_REQUESTED 派 implementer 改代码。
      - `ready` → 转正残留 draft PR（确定性 `github.mark_ready`，level-triggered 安全网；happy-path 转正
        归 deliver agent）。**排在 merge 前**：任何 PR 都不在 draft 态被合（见 `_classify` ⑪，Spec-0017）。
      - `merge` → 下放 merger agent 落合并（**不可逆**，故先经 `gates.assert_merge_allowed` 硬闸把守红线，
        且 `_classify` 把它排在最后一支、人的新评论排在最前一支）。
      - `reply` → 回一条评论（复用 `agents.replier` + 签名回帖）。

    各分支复用 `recipes.stages` 的竖切段 / 合并段。可配闸按 `config.stages` 三态内联路由（`skip` 已在
    `_sense` 归一成「已过闸」，故这里只会看到 agent / human）；确定性硬闸（head 前移 / 证据溯源戳 /
    round_cap）**恒机器、`skip` 关不掉**（内嵌在 `stages` 的交付段里）。动作幂等（已 merged 再合、已回过的
    评论再回都是 no-op）。

    **每个分支都有第二个出口：`needs-human`。** agent 在任一分支里判断「我没辙 / 这要人来定」——CI 是上游
    flaky、需求本身有歧义、要动的东西超出授权、连试两次都推不动——它就**打 `_LABEL_NEEDS_HUMAN` + 留一条
    说明理由的评论**，然后正常返回。`_reconcile` 下一圈 `_sense` 就读到该 label → 分支① TERMINAL → 收工，
    **轮询就此停止**。这是**一等出口，不是快路径**：正常的「干不动」都该从这里走完，护栏一（attempt 戳）与
    护栏二（看门狗）只兜「agent 忘了打 / 判错了 / 没意识到自己在空转」这三种它自己看不见的死法。这条契约由
    `_NEEDS_HUMAN_CONTRACT` 拼进每个分支的 agent 提示词（`context_text`），否则兜底会变成主路径。

    **硬超时**：整个动作（含其内部的 agent 子进程）超 `_AGENT_TIMEOUT_SECONDS` → 杀子进程 + 抛
    `_ActTimeout` → `_worker_loop` 捕获 → 持有者**自己**走 `_requeue_or_park`（释放行与锁，claimed 行永不
    成孤儿）。flock 只回答「进程在不在」，回答不了「进程活着但挂死」——这道闸补的正是那个洞。
    """
    facts = observed.facts
    timed = _TimedBackend(inner=backend, timeout_seconds=_AGENT_TIMEOUT_SECONDS, lock_fd=lock_fd)
    action = verdict.action
    stage_owner = config.stages.owner_of

    if action == _ACT_REPLY:
        return _do_reply(
            backend=timed, state=state, work_dir=work_dir, facts=facts, agent_id=agent_id
        )
    if action == _ACT_SOLVE:
        return _do_solve(backend=timed, state=state, work_dir=work_dir, config=config, facts=facts)
    if action == _ACT_REBASE:
        return route(
            owner=stage_owner(stage=agent_config.STAGE_CONFLICT),
            on_agent=lambda: _do_rebase(backend=timed, work_dir=work_dir, facts=facts),
            on_human=lambda: _park_gate(facts=facts, gate="conflict", agent_id=agent_id),
            on_skip=lambda: _park_gate(facts=facts, gate="conflict", agent_id=agent_id),
        )
    if action == _ACT_FIX_CI:
        return route(
            owner=stage_owner(stage=agent_config.STAGE_CI),
            on_agent=lambda: _do_fix_ci(backend=timed, work_dir=work_dir, facts=facts),
            on_human=lambda: _park_gate(facts=facts, gate="ci", agent_id=agent_id),
            on_skip=lambda: _park_gate(facts=facts, gate="ci", agent_id=agent_id),
        )
    if action == _ACT_E2E:
        return route(
            owner=stage_owner(stage=agent_config.STAGE_E2E),
            on_agent=lambda: _do_e2e(
                backend=timed, work_dir=work_dir, facts=facts, agent_id=agent_id
            ),
            on_human=lambda: _park_gate(facts=facts, gate="e2e", agent_id=agent_id),
            on_skip=lambda: _park_gate(facts=facts, gate="e2e", agent_id=agent_id),
        )
    if action == _ACT_REVIEW_OR_FIX:
        return route(
            owner=stage_owner(stage=agent_config.STAGE_REVIEW),
            on_agent=lambda: _do_review_or_fix(backend=timed, work_dir=work_dir, facts=facts),
            on_human=lambda: _park_gate(facts=facts, gate="review", agent_id=agent_id),
            on_skip=lambda: _park_gate(facts=facts, gate="review", agent_id=agent_id),
        )
    if action == _ACT_READY:
        # Spec-0017: 转正自愈支——level-triggered 安全网（happy-path 转正归 deliver agent）。零判断的机械
        # 动作（客观对 draft ∧ 已就绪完全决定该做什么），按 Spec-0064 分界留确定性 `github.mark_ready`，
        # 不为一行 `gh pr ready` 烧 LLM。不进 stages 三态策略点（无「谁把关」可选）。
        return _do_ready(facts=facts)
    if action == _ACT_MERGE:
        return route(
            owner=stage_owner(stage=agent_config.STAGE_MERGE),
            on_agent=lambda: _do_merge(backend=timed, state=state, work_dir=work_dir, facts=facts),
            on_human=lambda: _park_gate(facts=facts, gate="merge", agent_id=agent_id),
            on_skip=lambda: _park_gate(facts=facts, gate="merge", agent_id=agent_id),
        )
    raise ValueError(f"未知动作：{action!r}")


# Spec-0065/T2: **一等出口契约**——拼进每个 `_act` 分支派出去的 agent 的上下文。没有它，「干不动」只能靠
# 护栏兜（多烧一次 LLM 调用 + 多等一个看门狗阈值，且理由只能靠机械诊断猜），兜底就变成了主路径。
_NEEDS_HUMAN_CONTRACT = (
    "\n\n---\n"
    f"【一等出口】若你判断自己没辙、或这件事该由人来定（CI 是上游 flaky、需求本身有歧义、要动的东西超出"
    f"授权、连试两次都推不动），**不要空转、不要假装修好**：给该 issue/PR 打上 `{_LABEL_NEEDS_HUMAN}` "
    "label，并留一条说明理由的评论，然后正常收工。守夜会当场判定终态、停止轮询、把理由交给人——这比让"
    "看门狗超时叫人快得多，也便宜得多。"
)


def _do_reply(
    *, backend: Any, state: RuntimeState, work_dir: Path, facts: _Facts, agent_id: str
) -> str:
    """分支②：最新评论是人发的 → 派 replier 回一条签名评论（承旧串行 vigil 的 _reply_one_pr）。

    与其它分支一样拼上 `_NEEDS_HUMAN_CONTRACT`：人问的问题 replier 也可能答不了（要动的东西超出授权、需求
    本身有歧义），它同样需要那个一等出口，否则「答不了」只能靠看门狗兜。

    # Spec-0016/T4: 两条对称路径按 `pr_number` 分派——有 PR → PR 版原语（下），无 PR（且是已准入 issue）
    # → issue 版原语（`_do_reply_issue`）。issue #149：把回复从 PR 扩到 issue 页，只答疑不改代码。
    """
    pr_number = facts.pr_number
    if pr_number is None:
        return _do_reply_issue(
            backend=backend, state=state, work_dir=work_dir, facts=facts, agent_id=agent_id
        )
    news = identity.new_human_comments(
        pr_number=pr_number, since=state.get_cursor(pr_number=pr_number) or ""
    )
    if not news:
        return ""
    latest = news[-1]
    placeholders = context.for_reply(
        work_dir=work_dir,
        pr_number=pr_number,
        branch=github.pr_head_branch(pr_number=pr_number),
        comment=latest,
    )
    placeholders["context"] = f"{placeholders['context']}{_NEEDS_HUMAN_CONTRACT}"
    verdict = engine.run_agent(replier, backend=backend, **placeholders)
    identity.post_signed_comment(pr_number=pr_number, body=verdict["reply"], agent_id=agent_id)
    state.set_cursor(pr_number=pr_number, comment_id=latest.created_at)
    _log(message=f"↩ PR #{pr_number}：已回应人类评论")
    return verdict["reply"]


# Spec-0016/T4: issue 回复用的 agent-module 视图——`engine.run_agent` 恒读 `agent_module.PROMPT`，
# 故给它一个把 `PROMPT` 指向 `replier.ISSUE_PROMPT`（issue 语境、只答疑不改代码）、`OUTPUT_SCHEMA` 复用
# replier 同一 schema 的轻量命名空间。不新造 agent 模块（奥卡姆）：issue/PR replier 共用输出契约，只是
# 提示词分家。
_ISSUE_REPLIER = SimpleNamespace(PROMPT=replier.ISSUE_PROMPT, OUTPUT_SCHEMA=replier.OUTPUT_SCHEMA)


def _do_reply_issue(
    *, backend: Any, state: RuntimeState, work_dir: Path, facts: _Facts, agent_id: str
) -> str:
    """# Spec-0016/T4：分支②的 issue 支——已准入无-PR issue 上有新人类评论 → 派 replier 回一条签名评论。

    与 `_do_reply`（PR 支）逐环对称，只是每一环都换 issue 版原语：读经 `new_human_comments_on_issue`
    （游标取 `state.get_issue_cursor`）、占位符经 `context.for_issue_reply`（issue 语境提示词
    `replier.ISSUE_PROMPT`——只答疑不改代码，见 T3）、回帖经 `identity.post_signed_comment_on_issue`、
    游标推 `state.set_issue_cursor`。同样拼上 `_NEEDS_HUMAN_CONTRACT` 一等出口（答不了/超授权 → 主动叫人）。
    回帖后最新评论变我方签名 → 下一 tick `_sense` 的 `_latest_is_ours` True → 分支②停火（不重复回帖）。
    """
    kind, number = _split_subject(subject=facts.subject)
    if kind != _KIND_ISSUE:
        return ""  # 无 PR 的裸 PR subject 不存在；防御性返回
    news = identity.new_human_comments_on_issue(
        number=number, since=state.get_issue_cursor(number=number) or ""
    )
    if not news:
        return ""
    latest = news[-1]
    placeholders = context.for_issue_reply(work_dir=work_dir, issue_number=number, comment=latest)
    placeholders["context"] = f"{placeholders['context']}{_NEEDS_HUMAN_CONTRACT}"
    verdict = engine.run_agent(_ISSUE_REPLIER, backend=backend, **placeholders)
    identity.post_signed_comment_on_issue(number=number, body=verdict["reply"], agent_id=agent_id)
    state.set_issue_cursor(number=number, comment_id=latest.created_at)
    _log(message=f"↩ issue #{number}：已回应人类评论")
    return verdict["reply"]


def _do_solve(
    *,
    backend: Any,
    state: RuntimeState,
    work_dir: Path,
    config: agent_config.AgentConfig,
    facts: _Facts,
) -> str:
    """分支④：还没有 PR → 竖切（worktree → rfc(routed) → 开 draft PR → implement → deliver）。

    **不在此阻塞等 CI / 等 review**——那两支是 `_classify` 的分支⑦⑩，回到 `_reconcile` 的循环里自然会走到；
    在这里再嵌一个 review 循环（旧串行 vigil 的 run_solve 的做法）就是把分支表复制了一份。
    """
    kind, number = _split_subject(subject=facts.subject)
    if kind != _KIND_ISSUE:
        return ""  # 裸 PR 不可能走到 solve（它天生有 PR）
    issue = github.get_issue(number=number)
    branch = f"{_BRANCH_PREFIX}{number}"
    worktree = git.Workspace(work_dir=work_dir).prepare(
        issue_number=number, branch=branch, base=config.base
    )

    def _draft() -> None:
        stages.rfc(
            backend=backend,
            worktree=worktree,
            mode=stages.MODE_DRAFT,
            target=f"issue #{issue.number}「{issue.title}」",
            branch=branch,
            detail=issue.body,
            context_text=issue.body + _NEEDS_HUMAN_CONTRACT,
            require_delivered=False,
        )

    route(
        owner=config.stages.owner_of(stage=agent_config.STAGE_RFC),
        on_agent=_draft,
        on_human=_draft,
        on_skip=lambda: None,
    )
    pr = github.create_pr(
        branch=branch,
        base=config.base,
        title=f"feat: issue #{issue.number} {issue.title}".strip(),
        body=f"Closes #{issue.number}\n\nopenagents 守夜自动求解，待评审。",
        draft=True,
    )
    state.set_run(issue_number=number, status="pr-open", branch=branch, pr_number=pr.number)
    stages.implement(
        backend=backend,
        work_dir=worktree,
        issue_number=number,
        pr_number=pr.number,
        feedback="",
        context_text=issue.body + _NEEDS_HUMAN_CONTRACT,
    )
    report = stages.deliver(
        backend=backend,
        worktree=worktree,
        branch=branch,
        pr_number=pr.number,
        issue_number=number,
        # Spec-0065/T2: 交付段同样要给一等出口——推不上去（保护分支/权限/反复 rebase 打架）时，agent 得能
        # 主动打 needs-human，而不是硬着头皮 force-push 或空转到看门狗。
        context_text=_NEEDS_HUMAN_CONTRACT,
    )
    # Spec-0017/T2: 不再确定性直调 github.mark_ready——转正归 deliver agent（其完成判据含「PR 非 draft」）；
    # 万一那一枪脱靶，PR 残留 draft 由 `_classify` ⑪ 每 tick 复检、`_do_ready` 兜底转正（level-triggered）。
    _log(message=f"✓ issue #{number}：已开 PR #{pr.number}")
    return str(report.get("summary", ""))


def _do_rebase(*, backend: Any, work_dir: Path, facts: _Facts) -> str:
    """分支⑥：冲突 / base 前移 → 先试机械 `update_branch`（零 LLM），不行再下放 agent 解冲突。

    `update_branch` 只在「没冲突、只是落后」时成功；真冲突时它会失败 → 落到 `stages.conflict`（agent 按
    `_GIT_DELIVERY_PROTOCOL` 变基：`force-with-lease`、仅本分支、禁裸 force）。**先机械后 agent** 省的是
    绝大多数「只是 base 前移」的情形——那本就不需要模型。
    """
    pr_number = facts.pr_number or 0
    try:
        if github.update_branch(pr_number=pr_number, rebase=True):
            _log(message=f"↻ PR #{pr_number}：base 已并入（机械 update-branch，未叫 agent）")
            return "base 已并入（机械 update-branch）"
    except github.GithubError as exc:
        _log(message=f"… PR #{pr_number}：update-branch 不行（{exc}），下放 agent 解冲突")
    _, number = _split_subject(subject=facts.subject)
    result = stages.conflict(
        backend=backend,
        work_dir=work_dir,
        pr_number=pr_number,
        issue_number=number if facts.subject.startswith(_KIND_ISSUE) else 0,
        branch=github.pr_head_branch(pr_number=pr_number),
        context_text=_NEEDS_HUMAN_CONTRACT,  # 解不动冲突正是该主动交人的场景（一等出口，见 `_act`）
    )
    return str(result.get("summary", ""))


def _do_fix_ci(*, backend: Any, work_dir: Path, facts: _Facts) -> str:
    """分支⑧：当前 head 上 CI 红 → 把失败 check 的摘要喂给 implementer 去修。"""
    pr_number = facts.pr_number or 0
    logs = "\n".join(github.check_logs(pr_number=pr_number))
    report = stages.implement(
        backend=backend,
        work_dir=_pr_worktree(work_dir=work_dir, facts=facts),
        issue_number=_issue_number_of(facts=facts),
        pr_number=pr_number,
        feedback=f"[ci] CI 红了，请据失败日志修复：\n{logs}",
        context_text=_NEEDS_HUMAN_CONTRACT,
    )
    return str(report.get("summary", ""))


def _do_e2e(*, backend: Any, work_dir: Path, facts: _Facts, agent_id: str) -> str:
    """分支⑨：e2e 证据缺失 / 陈旧 → 派 tester 跑 e2e，贴一条**带 head_sha 溯源戳**的证据评论。

    戳里的 head 就是**这一版代码**的 head（`facts.head_sha`）——下一圈 `_sense` 读回来与当前 head 比对：
    相等 ⇒ 这份证据是给这版跑的 ⇒ 分支⑨过；head 一前移 ⇒ 证据自动作废 ⇒ 重跑。证据不能只说「跑过了」
    （张冠李戴：拿旧版的绿证据放行新版代码），Spec-0055 已踩过。

    tester 判 REWORK（e2e 没过）时**不盖戳**——盖了就等于用一份失败的证据放行。让 fp 保持不变 → 下一圈
    `_reconcile` 见零进展 → 盖 attempt 戳 → 看门狗兜底叫人（或 agent 自己打 needs-human，那是主路径）。
    """
    pr_number = facts.pr_number or 0
    verdict = engine.run_agent(
        tester,
        backend=backend,
        work_dir=_pr_worktree(work_dir=work_dir, facts=facts),
        context=_NEEDS_HUMAN_CONTRACT,
        pr_number=pr_number,
        issue_body="",
    )
    if verdict["verdict"] != "PASS":
        _log(message=f"✗ PR #{pr_number}：e2e 未过（{verdict['reason']}），不盖证据戳")
        return str(verdict["reason"])
    identity.post_signed_comment(
        pr_number=pr_number,
        body=(
            f"{_E2E_MARKER}{facts.head_sha} -->\n"
            f"✅ e2e 通过（head `{_short(sha=facts.head_sha)}`）。\n\n{verdict['reason']}"
        ),
        agent_id=agent_id,
    )
    _log(message=f"✓ PR #{pr_number}：e2e 通过，已贴证据戳（head {_short(sha=facts.head_sha)}）")
    return str(verdict["reason"])


def _do_review_or_fix(*, backend: Any, work_dir: Path, facts: _Facts) -> str:
    """分支⑩：无裁决 / 裁决陈旧 → 派 reviewer 审；已是 CHANGES_REQUESTED@当前 head → 派 implementer 改。

    裁决落 label 时**把当前 head 的 sha7 嵌进 label 名**（`review-approved:<sha7>`）——裁决绑 commit，不是
    一个恒真属性。同时**先摘掉该 PR 上所有陈旧的 review-\\* label**：留着它们不影响正确性（sha 对不上就不
    被承认），但会让人在 UI 上看到一排互相矛盾的裁决。
    """
    pr_number = facts.pr_number or 0
    if facts.review_state == _REVIEW_CHANGES_REQUESTED and facts.review_commit_id == _short(
        sha=facts.head_sha
    ):
        report = stages.implement(
            backend=backend,
            work_dir=_pr_worktree(work_dir=work_dir, facts=facts),
            issue_number=_issue_number_of(facts=facts),
            pr_number=pr_number,
            feedback="[review] 评审要求返工，请据上一轮 review 意见修改",
            context_text=_NEEDS_HUMAN_CONTRACT,
        )
        return str(report.get("summary", ""))

    verdict = stages.review(
        backend=backend,
        work_dir=_pr_worktree(work_dir=work_dir, facts=facts),
        pr_number=pr_number,
        issue_body=_issue_body_of(facts=facts),
        context_text=_NEEDS_HUMAN_CONTRACT,
    )
    _clear_review_labels(pr_number=pr_number, labels=facts.labels)
    prefix = (
        _LABEL_REVIEW_APPROVED_PREFIX
        if verdict["verdict"] == "PASS"
        else _LABEL_REVIEW_CHANGES_PREFIX
    )
    label = f"{prefix}{_short(sha=facts.head_sha)}"
    github.ensure_label(name=label, description="openagents 守夜：绑 head sha 的评审裁决")
    github.add_label(pr_number=pr_number, name=label)
    _log(message=f"✓ PR #{pr_number}：评审裁决 {label}")
    return str(verdict["reason"])


def _do_ready(*, facts: _Facts) -> str:
    """分支⑪：全绿 + approved@head 但仍 draft → 确定性转正（`github.mark_ready`，level-triggered 安全网）。

    happy-path 转正由 deliver agent 顺手做（其完成判据含「PR 非 draft」）；本支是那一枪脱靶后的兜底——
    `is_draft` 是每 tick 复检的一等事实，故这里天然幂等/自愈（`mark_ready` 对已非 draft 的 PR 是 no-op，
    且下一 tick `_sense` 读回 `is_draft=False` → 走到 ⑫ merge）。零判断的机械动作，按 Spec-0064 分界留确定
    性、不派 agent（为何不派新 promoter agent 见 Spec-0017 Rationale）。
    """
    pr_number = facts.pr_number or 0
    github.mark_ready(pr_number=pr_number)
    _log(message=f"✓ PR #{pr_number}：已转正（draft → ready），下一 tick 判 merge")
    return "已转正（mark ready）"


def _do_merge(*, backend: Any, state: RuntimeState, work_dir: Path, facts: _Facts) -> str:
    """分支⑫：全绿 + `review-approved:<当前 head 的 sha7>` + 非 draft → 下放 merger agent 合（**不可逆**）+ 关 issue + 置 done。

    Spec-0017/T2：合并动作经 `stages.merge` 下放 merger agent——但先经确定性 `gates.assert_merge_allowed`
    实时复读 CI + label 把守不可逆红线（闸不放行即抛，决不派 agent 合未审代码），放行后才派 merger 落
    `gh pr merge`。`head_sha` 绑当前 head（防 `_sense→_act` 间 head 前移的 TOCTOU）。
    """
    pr_number = facts.pr_number or 0
    stages.merge(
        backend=backend,
        pr_number=pr_number,
        head_sha=facts.head_sha or "",
        work_dir=work_dir,
        context_text=_NEEDS_HUMAN_CONTRACT,
    )
    number = _issue_number_of(facts=facts)
    if number:
        state.set_run(
            issue_number=number,
            status="done",
            branch=f"{_BRANCH_PREFIX}{number}",
            pr_number=pr_number,
        )
        github.close_issue(number=number)
    _log(message=f"✓ PR #{pr_number}：已合并")
    return "merged"


def _park_gate(*, facts: _Facts, gate: str, agent_id: str) -> str:
    """可配闸 owner=human → 挂 `needs-human` 停等人（`_classify` 下一圈判 TERMINAL、轮询停止）。"""
    _park_needs_human(
        subject=facts.subject,
        body=(
            f"⏸ openagents 守夜：`{gate}: human`——本闸归人，守夜停在这里等你。\n\n"
            "处理完摘掉本 label，守夜会自动重新接管。"
        ),
        agent_id=agent_id,
    )
    return f"{gate}: human"


def _clear_review_labels(*, pr_number: int, labels: frozenset[str]) -> None:
    """摘掉 PR 上所有旧的 `review-*:<sha7>` 裁决 label（新裁决落下前先清场，免得 UI 上一排矛盾裁决）。"""
    for label in sorted(labels):
        if label.startswith((_LABEL_REVIEW_APPROVED_PREFIX, _LABEL_REVIEW_CHANGES_PREFIX)):
            github.remove_label(pr_number=pr_number, name=label)


def _pr_worktree(*, work_dir: Path, facts: _Facts) -> Path:
    """给 PR 分支备好 worktree 供 agent 改代码（承旧串行 vigil 的 _ensure_pr_worktree）。可 monkeypatch。

    **worktree 目录必须按 subject 分开。** `Workspace.ensure` 用 `issue_number` 当目录名
    （`.worktrees/issue-{n}`）且**目录已存在就直接返回、不查当前在哪个分支上**——所以裸 PR 若都按「无 issue
    归属 → 0」去要 worktree，`pr:12` 和 `pr:13` 会拿到**同一个** `.worktrees/issue-0`：两个 worker 的 agent
    在同一个目录里同时改代码，且后来者其实站在前者的分支上，会把改动推到**别人的 PR** 上去。subject 级互斥
    （flock）拦不住这个——它们本就是两个不同的 subject，共享的是**资源**。

    故裸 PR 用 **PR 号**当目录键：GitHub 的 issue 与 PR 共用一套编号，`pr:N` 与 `issue:N` 不可能同时存在，
    不会与 issue 的 worktree 撞名。
    """
    kind, number = _split_subject(subject=facts.subject)
    if kind == _KIND_ISSUE:
        return git.Workspace(work_dir=Path(work_dir)).ensure(
            issue_number=number, branch=f"{_BRANCH_PREFIX}{number}"
        )
    return git.Workspace(work_dir=Path(work_dir)).ensure(
        issue_number=number, branch=github.pr_head_branch(pr_number=facts.pr_number or number)
    )


def _issue_number_of(*, facts: _Facts) -> int:
    """subject 的 issue 归属编号；裸 PR（`pr:N`）→ 0（无 issue 归属，优雅降级）。"""
    kind, number = _split_subject(subject=facts.subject)
    return number if kind == _KIND_ISSUE else 0


def _issue_body_of(*, facts: _Facts) -> str:
    """reviewer 要的验收口径（issue 正文）；裸 PR 无 issue 归属 → 空串。"""
    number = _issue_number_of(facts=facts)
    return github.get_issue(number=number).body if number else ""


def _has_attempt_stamp(*, facts: _Facts, fp: str) -> bool:
    """护栏一的读侧：GitHub 上是否已存在**同一个 `fp`** 的 attempt 戳（`_ATTEMPT_MARKER`）。

    有 → 说明我在**完全相同的状态**下已经出过手且一个字节没推动 → 生产者把 ACTIONABLE 降级为
    `QUIET(awaiting-effect)`、不入队。**只需一个 bit，不需要计数**：同证据、同 prompt、再叫一次，期望收益
    接近零；而 park 是廉价可逆的（人摘 label 即复活），早叫人几乎没代价。真正的瞬时故障重试属于 **agent
    内部**的事，不该冒泡成编排层的一个可调参数。

    戳随 fp 变化自动作废——任何真实进展都会改 fp（见 `_fingerprint`），旧戳就此失配、subject 正常重新入队。
    """
    return any(
        f"{_ATTEMPT_MARKER} fp={fp} -->" in comment.body for comment in _comments(facts=facts)
    )


def _post_attempt_stamp(*, facts: _Facts, fp: str, conclusion: str, agent_id: str) -> None:
    """护栏一的写侧：agent 零进展收工时，在 PR/issue 下盖一条带 `fp` 的签名评论。

        <!-- openagents:attempt fp=9f2a1c… -->
        本轮结论：`test_upload_timeout` 为 flaky（近 20 次 CI 中随机失败 4 次，均为超时，与本 PR 改动
        无关）。未做任何代码变更。

    **只在「fp 未变」这个出口盖**（见 `_reconcile`）——正常推进的出口不盖，否则每次成功推进都留一枚马上就会
    失配的死戳。`conclusion` 是 agent 自己的话：它既是给下一轮的护栏，也是给人看的工作日志（人来接手时，第一
    件想知道的就是「上一个 agent 试了什么、为什么没成」）。

    戳数天然有上限（同 fp 一条，fp 变 = 真有新情况），一个正常 PR 约 3–6 条。
    """
    body = (
        f"{_ATTEMPT_MARKER} fp={fp} -->\n"
        f"🔁 openagents 守夜：本轮出手后状态**一个字节未变**（零进展），已收工、不再重叫 agent。\n\n"
        f"agent 自述结论：{conclusion or '（无）'}"
    )
    if facts.pr_number is not None:
        identity.post_signed_comment(pr_number=facts.pr_number, body=body, agent_id=agent_id)
    else:
        github.issue_comment(
            number=_issue_number_of(facts=facts), body=identity.sign(body=body, agent_id=agent_id)
        )
    _log(message=f"🔁 {facts.subject}：零进展，已盖 attempt 戳（fp={fp}）")


def _comments(*, facts: _Facts) -> list[github.Comment]:
    """subject 的评论流：有 PR 读 PR 的，否则读 issue 的（attempt 戳落处随之）。"""
    if facts.pr_number is not None:
        return github.list_comments(pr_number=facts.pr_number)
    return github.list_issue_comments(number=_issue_number_of(facts=facts))


def _park_needs_human(*, subject: str, body: str, agent_id: str) -> None:
    """给 subject 打 `needs-human` + 贴**签名**理由评论（幂等）。`_classify` 下一圈判 TERMINAL → 轮询停止。

    # Spec-0065/T2: 理由评论**必须签名**，否则我方评论会被当成人说的话。两处读评论流的地方都按
    「有没有我方签名」区分人机：`_latest_is_ours`（守候段：最新一条不是我方 → 有人说话了 → 叫 replier）
    与 `_human_replies`（准入段：无签名 → 人回话了 → 叫 admitter）。park 的理由评论恰恰是**最后一条**，
    且每条 park 文案都在教人「说清楚后摘掉 label」——人照做（只摘 label、不评论）之后，谓词重新活过来，
    读到的最新一条就是**我们自己写的 park 理由**：不签名 → 判成「人回话了」→ agent 对着自己写的话开会。
    签名把这个自问自答的环从源头掐死（这正是 `identity` 签名纪律存在的理由）。

    # Spec-0065/T2: 理由评论**同一段话只贴一次**。park 是 level-triggered 的：人摘掉 `needs-human` 却没
    改变任何事实（读岔了、手滑、label 自动化），下一 tick 会原样再 park 一次——理由一字不差，却又是一条
    新评论。label 本身幂等（打第二遍是空操作），评论不是。故先读回评论流，同一段理由已经贴过就只补 label。
    """
    kind, number = _split_subject(subject=subject)
    signed = identity.sign(body=body, agent_id=agent_id)
    if kind == _KIND_ISSUE:
        github.issue_add_label(number=number, name=_LABEL_NEEDS_HUMAN)
        if not _already_said(comments=github.list_issue_comments(number=number), body=body):
            github.issue_comment(number=number, body=signed)
    else:
        github.add_label(pr_number=number, name=_LABEL_NEEDS_HUMAN)
        if not _already_said(comments=github.list_comments(pr_number=number), body=body):
            github.post_comment(pr_number=number, body=signed)
    _log(message=f"⏸ {subject}：已挂 {_LABEL_NEEDS_HUMAN}，交人接手")


def _already_said(*, comments: list[github.Comment], body: str) -> bool:
    """这段话我方是不是已经原样说过了（比未签名的正文，签名里的 agent_id 每进程不同，不能比全文）。"""
    return any(
        identity.parse_agent_id(body=comment.body) is not None and body.strip() in comment.body
        for comment in comments
    )


# --------------------------------------------------------------------------------------------------
# `_act` 的硬超时：flock 只回答「进程在不在」，回答不了「进程活着但挂死在一个不返回的调用上」。
# --------------------------------------------------------------------------------------------------


class _TimedBackend:
    """给 backend 的 `run` 套一层**硬墙钟**：超 `timeout_seconds` → 杀掉这次调用起的进程树 + 抛 `_ActTimeout`。

    为什么套在 backend 而不是包整个 `_act`：agent 调用是 `_act` 里唯一可能**永不返回**的东西（网络/模型
    挂起），而 backend 是它的唯一入口。套在这里，超时能精确定位到「哪一次 agent 调用挂了」，也能拿到该次
    调用起的子进程去杀——包在外面就只能笼统地杀掉本进程的所有子进程，会误杀**其它 worker 正在跑的 agent**。

    **子进程归属靠 backend 自报，不靠猜。** 在跑 agent 的那个线程里先 `proc.track()` 开桶，backend `Popen`
    之后 `proc.publish(pid=…)` 自报；超时方按 `thread.ident` 取桶、`proc.kill_tree` 连同后代一起杀。早前用
    「调用前后 diff 本进程子进程集合」认领是错的——生产者线程同时在跑 `gh`/`git`（同样是本进程的子进程），
    K 个 worker 也彼此并发：diff 会把别人的 `gh` 认成自己的 agent，于是超时时**杀错进程、真挂死的 agent
    还活着继续 push**，双跑就从这个洞里漏出来（而这道闸正是 flock 覆盖不到的那个洞）。

    抛出后：`_worker_loop` 捕获 `_ActTimeout` → **直接 park 交人**（不回队重试）。因为「杀干净了」只是尽力
    而为（in-proc backend / 没自报 PID 的 backend 杀不着），把一个可能还活着的 agent 的活重新发出去正是双跑；
    而挂死 30 分钟本就是该叫人的事。其它异常（gh 抖动等）仍走回队重试。
    """

    def __init__(self, *, inner: Any, timeout_seconds: int, lock_fd: int | None) -> None:
        self._inner = inner
        self._timeout_seconds = timeout_seconds
        self._lock_fd = lock_fd

    def run(self, *, work_dir: Path, task: str, context: str) -> Any:
        """跑一次 agent；超时则杀进程树并抛 `_ActTimeout`（签名与 `backends.base` 一致，可无缝替换）。"""
        box: dict[str, Any] = {}
        thread = threading.Thread(
            target=self._call,
            kwargs={"box": box, "work_dir": work_dir, "task": task, "context": context},
            daemon=True,
        )
        thread.start()
        thread.join(timeout=self._timeout_seconds)
        spawned = proc.untrack(thread_id=thread.ident or 0)
        proc.release_fds(thread_id=thread.ident or 0)
        if thread.is_alive():
            for pid, handle in sorted(spawned.items()):
                proc.kill_tree(pid=pid, handle=handle)  # 句柄验明正身，绝不杀 PID 复用后的无辜进程
            raise _ActTimeout(
                f"agent 调用超过 {self._timeout_seconds}s 未返回，已杀进程树 {sorted(spawned)}"
            )
        if "error" in box:
            raise box["error"]
        return box["result"]

    def _call(self, *, box: dict[str, Any], work_dir: Path, task: str, context: str) -> None:
        """在子线程里跑真 backend，把结果/异常装箱回主线程（超时的话这个线程会被丢弃，其进程树已被杀）。

        两件事必须在**这个**线程里做（backend 就在这个线程里起子进程）：
        - `proc.track()` 开认领桶——backend 自报的 PID/句柄落进这个桶，只属于这次调用。
        - `proc.hold_fd(fd=lock_fd)` 登记 flock 的 fd，让 agent 子进程**继承**它。于是「谁在干活谁持锁」：
          守夜进程被 SIGKILL/OOM 打死时，它起的 agent 是被孤儿化而不是被杀，锁仍被那个孤儿持着 →
          `_reclaim_dead` 抢不到 → 那行不会被打回队列重领 → 双跑的最后一个入口封死。生产者线程的
          triage/curator 调用没有认领的行（`lock_fd is None`），只套超时，不传 fd。
        """
        # 登记也在 try 里：`hold_fd` 会碰 fd（`set_inheritable` 遇坏 fd 抛 EBADF）。它若在 try 外抛，这个线程就
        # 带着一个既无 result 也无 error 的空箱子死掉，`run()` 取 box["result"] 得到 KeyError——把一个可诊断的
        # 失败变成一桩悬案。
        try:
            proc.track()
            if self._lock_fd is not None:
                proc.hold_fd(fd=self._lock_fd)
            box["result"] = self._inner.run(work_dir=work_dir, task=task, context=context)
        except BaseException as exc:  # noqa: BLE001 —— 原样转交调用线程重抛
            box["error"] = exc


# --------------------------------------------------------------------------------------------------
# fleet：多仓库 = 每仓一子进程跑一次 run_vigil（gh/git 绑 cwd，必须进程隔离；承旧串行 vigil 的 run_fleet）。
# --------------------------------------------------------------------------------------------------


def _run_repo_inline(
    *,
    repo: agent_config.RepoPlan,
    agents: agent_config.AgentPolicy,
    release: agent_config.ReleasePolicy,
    once: bool,
) -> None:
    """在本进程跑单仓库 `run_vigil`——延迟 import cli 工厂构造 backend/state/身份（沿用「命令体内延迟 import」）。"""
    from openagents import cli
    from openagents.utils import config as config_mod

    ctx = config_mod.resolve_project()
    if ctx is None:
        raise RuntimeError(f"{repo.path} 不是 git 仓库，无法守夜")
    backend, state, agent_id = cli._vigil_deps_for(ctx=ctx)
    run_vigil(
        backend=backend,
        state=state,
        work_dir=ctx.repo_root,
        config=_repo_as_config(repo=repo, agents=agents, release=release),
        once=once,
        agent_id=agent_id,
    )


def _repo_as_config(
    *,
    repo: agent_config.RepoPlan,
    agents: agent_config.AgentPolicy,
    release: agent_config.ReleasePolicy,
) -> agent_config.AgentConfig:
    """把单个 `RepoPlan` 包成 `run_vigil` 要的 `AgentConfig`（该仓 resolved stages + 顶层共享 agents/release）。"""
    return agent_config.AgentConfig(
        version=1,
        agents=agents,
        stages=repo.stages,
        release=release,
        interval=repo.interval,
        base=repo.base,
        labels=repo.labels,
        repos=[repo],
    )


def _run_repo_entry(*, plan: agent_config.RepoPlan, log_queue: Any, once: bool) -> None:
    """子进程真实入口：`os.chdir` 钉 cwd → 跑单仓 `run_vigil`，任何失败转一行干净日志 + 非零退出。"""
    from openagents.utils import fleet as fleet_util

    os.chdir(plan.path)
    writer = fleet_util._QueueWriter(name=plan.name, log_queue=log_queue)
    original_stderr = sys.stderr
    sys.stderr = writer
    try:
        _run_repo_inline(
            repo=plan,
            agents=agent_config.AgentPolicy(backends={}),
            release=agent_config.ReleasePolicy(),
            once=once,
        )
    except KeyboardInterrupt:
        raise
    except BaseException as exc:  # noqa: BLE001 —— 子进程兜底：任何失败转干净一行
        log_queue.put((plan.name, f"✗ 守夜失败：{exc}"))
        raise SystemExit(1) from exc
    finally:
        writer.flush()
        sys.stderr = original_stderr


def _default_spawn(*, plan: agent_config.RepoPlan, log_queue: Any, once: bool) -> Any:
    """真正起一个子进程跑 `_run_repo_entry`（`RepoPlan` 可 pickle，满足 spawn 启动方式）。"""
    import multiprocessing

    process = multiprocessing.Process(
        target=_run_repo_entry,
        kwargs={"plan": plan, "log_queue": log_queue, "once": once},
        name=plan.name,
        daemon=True,
    )
    process.start()
    return process


def _log(*, message: str) -> None:
    """守夜进度打到 stderr，保证无人值守时仍有可观测轨迹。"""
    print(message, file=sys.stderr, flush=True)
