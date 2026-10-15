# 联合发布流程与待办

本轮为源码整理，尚未发布 tag、Release、镜像或变更仓库可见性。两仓独立版本化，使用兼容清单把一组版本连接起来，不要求版本号相同。

## 基线与冻结

`release/compatibility.json` 的 `baseline_commit` 保留整理前的审计来源，`openagents.integration_commit` 则记录当前跨仓 CI 使用的完整 SHA，**两者都不是整理完成后的正式发行版本**。整理 PR 合并并通过检查后，从双方目标分支取最终提交，生成发布资产中的完整 manifest，填写两仓 SHA/tag、NexAU、seed Harness tree、容器 digest、配置 profile、平台及验证结果。避免在提交内部记录自身 commit hash。

两仓最终均从 main 发布。OpenAgents 功能分支已通过 [PR #185](https://github.com/Curry09/OpenAgents/pull/185) 合入 main，合并提交为 `1d4976c9a9e844037ddcadef8649aacb33edd950`。`chore/opensource-prep` 尚待评审合并；正式 tag 应包含这批许可、安装和 CI 整理改动。项目/前端/桌面组件版本可以不同，Release notes 解释各自范围。NexAU 的 extra 含固定 Git 来源，当前优先源码/GitHub wheel 发布；PyPI 发行前需另行验证 direct-reference 依赖政策与分发方案。

## 已纳入本轮代码的检查

- 锁定依赖安装、Python lint/format/test。
- auto-designer 的 evaluation 测试、前端测试/构建和实际两仓配置契约。
- OpenAgents 基础 wheel 仓外安装、可选 NexAU 导入、desktop typecheck/test/bundle。
- 公开快照的敏感哨兵回归测试；离线演示显式使用脚本客户端。

GitHub CI 的跨仓 checkout 要求对方仓库可读；首次公开前若仍是私仓，需要维护者设置只读仓库 secret `OPENAGENTS_READ_TOKEN`（workflow 不持久化该 checkout 凭证）或在受信任本地完成该项，不能把个人 token 写进 workflow。先公开可被读取的 OpenAgents，再公开/启用依赖它的 auto-designer CI。

## 正式公开前仍需完成

- [ ] 合成用户 + 自有任务的两轮真实闭环 demo，以及未参与开发者按文档完成一次安装/试用。
- [ ] Docker/Gitea/模型 canary：R1 反馈→需求→PR→合并，R2 users-only；另测停止/恢复及终态失败不误放行。
- [ ] 复测旧消息归属、子 Agent 停滞、撤回、反馈证据被驳回后不被 PM 重新当作事实等研究回归案例。
- [ ] 完整 Git 历史和 release 资产的秘密扫描；逐项处理，不无证据地重写历史。
- [ ] THIRD_PARTY.md 中人物画像、任务数据、vendored 来源的逐项许可与分发决定。
- [ ] 两侧 `npm audit` 告警评估和修复/书面处置，升级后重新验证。
- [ ] 固定并验证容器 digest；镜像构建/真实运行不能用 Python 测试结果代替。
- [ ] 检查分支保护必需状态、私密漏洞报告、仓库描述与双方链接。

## 发布顺序

1. OpenAgents 的功能合并已完成；继续将 `chore/opensource-prep` 评审合入 main。随后更新 auto-designer 的 OpenAgents pin、复测契约并将其整理 PR 合入 main，跑离线与真实验收。
2. 构建 OpenAgents wheel、源码包，以及约定的镜像；auto-designer 保持源码发行。使用不可变版本名，生成校验和、manifest、Release notes 和已知限制。
3. 先准备依赖方可引用的 OpenAgents 版本，再冻结 auto-designer 指向该版本；先以 draft/prerelease 验证安装与下载。
4. 维护者确认上述待办与资产后，执行正式 tag、Release 和可见性变更；双方 Release 互相链接。
5. 若验收失败，修复后发新的候选版本，不移动已有正式 tag。旧版本兼容组合继续保留。

## 更新联合版本时需要同步的引用

- auto-designer 的 `.github/workflows/ci.yml` 中 `integration` checkout `ref`：固定已验证的 OpenAgents 完整 SHA，不写移动的 `main`。
- 两仓 `release/compatibility.json` 的 `openagents.integration_commit`：与上述 ref 一致；保留历史 `baseline_commit` 供追溯。
- Quickstart 的 clone/checkout 示例：采用同一兼容组合；正式发布后补版本 tag 与对应 SHA。
- 构建镜像时使用该 OpenAgents checkout；发行资产记录实际镜像 digest，不能仅更新 Git ref 就宣称旧镜像含有新代码。

流程为：合并整理改动 → 更新包版本与发布说明 → 固定候选提交并验证 → 打不可变 tag、构建和验收 Release 资产。候选提交到正式 tag 若有变化，应重新验证；已有正式 tag 不移动。

## Evidence transport rollout (Spec-0092)

Deploy the gzip/ZIP reader before enabling ZIP publication in auto-designer. Record the
actual executable or image identity and run `openagents observation-capabilities --json`
in that environment with `OPENAGENTS_NO_SELF_UPDATE=1`. Keep self-update disabled in
new-path delivery processes so the checked reader remains the selected runtime.

Run `uv run --locked python scripts/check_observation_reader.py` for the offline fixture
contract, then use auto-designer's cross-repository check with the pinned producer and
reader. Separately verify synthetic evidence on self-hosted Gitea and Gitea.com, in the
actual E2B and container/proxy deployment paths. Require actual read-only files and
verified session scope; continued delivery after an evidence warning is not a pass.

Old gzip artifacts and handles need no migration. Reverting the publisher is safe only
where the selected site still accepts gzip and direct same-origin downloads. On
Gitea.com, stop new dispatches if the old transport cannot work; do not silently switch
formats within a resumed experiment. Do not publish future commit/image digests as if
already validated. Deployment pins and live probe results belong to the paired release.

## 执行条件协议的联合发布（Spec-0093）

本次实现基于 Gitea.com reader 候选 `a752e8830a13f44d97a3043d1f3e8dd16bd8d8aa`；该值是开发基线，不代表此次功能已发布。合并时先理顺该 reader 基线，再将已通过联合验收的实际提交固定到发布端。不得预写未来 SHA 或修改既有实验的冻结版本。

新增协商项为 `execution_evidence` schema 1，以及可信项目配置 `execution_evidence.required`。发布端确认实际安装具有 required dispatch 能力后才启用。两仓共享 `tests/fixtures/execution_evidence_contract.json` 的 wire 内容；发布前要比较 fixture、运行 reader 最终上下文探针及发布端真实 gzip/ZIP readback。私有评分计划、答案、原始 verifier 日志及凭证不进入该接口。

默认 standard 的实际起草角色为 drafter；显式 v0.2 使用 spec_writer/developer。两条路径均通过统一 engine 注入。其他 flow 可复用同一机制，但未单独验证时不将其宣传为此次已验收范围。模型行为 canary 与确定性送达测试分别记录，见 [执行条件保留验收记录](validation/execution-contract-preservation.md)。
