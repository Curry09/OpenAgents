# 联合发布流程与待办

本轮为源码整理，尚未发布 tag、Release、镜像或变更仓库可见性。两仓独立版本化，使用兼容清单把一组版本连接起来，不要求版本号相同。

## 基线与冻结

`release/compatibility.json` 记录整理前已审计的来源提交，**不是本次修改完成后的发行 SHA**。整理 PR 合并并通过检查后，从双方目标分支取最终提交，生成发布资产中的完整 manifest，填写两仓 SHA/tag、NexAU、seed Harness tree、容器 digest、配置 profile、平台及验证结果。避免在提交内部记录自身 commit hash。

两仓最终均从 main 发布。OpenAgents 当前功能基线位于 auto-designer/v0.2；本次核对 main 无独有提交，该功能分支领先 16 个提交，可快进收敛。先评审这批功能及整理改动并合入 main，再打联合候选 tag；不要从尚未纳入新版功能的旧 main 发布。项目/前端/桌面组件版本可以不同，Release notes 解释各自范围。NexAU 的 extra 含固定 Git 来源，当前优先源码/GitHub wheel 发布；PyPI 发行前需另行验证 direct-reference 依赖政策与分发方案。

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

1. OpenAgents 将 auto-designer/v0.2 的 16 个提交与本次整理改动评审后收敛进 main（可分两个 PR），auto-designer 整理 PR 合入 main；记录最终兼容组合，跑离线与真实验收。
2. 构建 OpenAgents wheel、源码包，以及约定的镜像；auto-designer 保持源码发行。使用不可变版本名，生成校验和、manifest、Release notes 和已知限制。
3. 先准备依赖方可引用的 OpenAgents 版本，再冻结 auto-designer 指向该版本；先以 draft/prerelease 验证安装与下载。
4. 维护者确认上述待办与资产后，执行正式 tag、Release 和可见性变更；双方 Release 互相链接。
5. 若验收失败，修复后发新的候选版本，不移动已有正式 tag。旧版本兼容组合继续保留。
