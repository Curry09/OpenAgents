---
number: "0092"
title: 兼容 Gitea.com 的证据读取与能力声明
issue: 0
slug: gitea-com-evidence-reader
summary: 兼容旧 gzip 证据并读取 ZIP，限定签名下载边界，为 auto-designer 提供真实运行时能力检查与联合验收。
e2e:
  intent: 同一证据在旧自建与 Gitea.com 路径中真实被 reader 获取且旧路径无回归。
  method: 使用合成授权证据和独立探针 issue，验证 gzip/ZIP 两种包在真实 prepare 中产生正确只读副本；分别检查实际部署能力、重定向认证边界和拒绝用例。
architecture:
  objective: 在原 issue 证据边界支持 ZIP 与 Gitea.com，同时保持旧 gzip 和角色语义。
  constraints:
    - 原 gzip/缺 encoding 句柄有效；内容授权校验不变。
    - 仅明确的 Gitea.com R2 profile 可跨域，且不携带 Gitea 认证。
    - 能力检查离线只读，不触发自更新。
  non-goals:
    - 不增加任意 URL 下载器，不修改普通 forge API 或角色流程。
  candidates:
    - id: additive-transport
      layer: evidence transport
      boundary:
        - 当前 issue 成员附件
        - 明确编码 envelope
        - 实际 executable 能力
      evidence:
        - gzip 跨仓基线通过
        - Gitea.com ZIP/303 探针
        - 旧 reader BadGzipFile
      tradeoffs: 维护两种编码及固定托管下载策略。
    - id: replace-all
      layer: protocol
      boundary:
        - 全部历史附件与 reader
      evidence:
        - 现有部署默认 gzip
      tradeoffs: 不必要地要求所有自建用户升级和迁移。
  selected: additive-transport
  affected-components:
    - observations.evidence
    - utils.gitea
    - observations.capabilities
    - cli
  failure-modes:
    - 不得把取证降级当成功。
    - 不得向对象存储泄露 Gitea 认证。
    - 不得用能力查询触发软件升级。
verification:
  behavior-cases:
    - id: BC1
      polarity: positive
      stimulus: 旧 gzip 与合法 ZIP issue 证据分别进入 prepare。
      expected: 得到匹配 session/digest 的只读历史文件。
      observation: 真实 prepare 联合检查及离线 fixture。
    - id: BC2
      polarity: negative
      stimulus: 未知编码、坏包、非成员附件或未经允许的跳转。
      expected: 有界拒绝且不发送跨源认证。
      observation: 解码和传输负例、真实 header 检查。
    - id: BC3
      polarity: positive
      stimulus: 空目录无凭证禁网调用能力命令。
      expected: 仅返回 JSON，无更新、文件创建或模型调用。
      observation: CLI 子进程测试与运行镜像检查。
  repository-invariants:
    - 普通 CLI 命令与 GitHub 流程不受影响。
    - 旧 gzip 与既有授权/摘要/路径防护保持。
  exemptions: []
tasks:
  - id: T1
    title: 兼容旧句柄的双格式证据解码
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/observations/evidence.py
      - tests/test_observation_evidence.py
    scope: 默认 gzip 并明确读取 encoding；有界解压单文件 ZIP 后复用原 issue/session/path/manifest 校验与只读交接。
    acceptance: 旧/显式 gzip 与 ZIP 经真实 prepare 成功；未知编码、坏包、跨 issue、恶意 ZIP 和超限均拒绝。
  - id: T2
    title: 仅针对 Gitea.com 的受限签名下载
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/utils/gitea.py
      - tests/test_observation_transport.py
    scope: 保留成员验证与同源直接下载，仅从认证附件入口允许一次规定 R2 跳转；不修改普通 REST 策略。
    acceptance: 自建旧路径及合法托管跳转通过；API/伪装域/二次跳转/坏状态/预算和 token/cookie/netrc 泄漏负例通过。
  - id: T3
    title: 无副作用的实际 reader 能力命令
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - openagents/observations/capabilities.py
      - tests/test_observation_capabilities.py
      - tests/test_cli.py
    scope: 注册并在自更新之前早分发 observation-capabilities，返回与真实实现绑定的格式/策略/预算 JSON。
    acceptance: 空目录无凭证禁网返回单个 JSON，无文件或模型/forge/git/uv 调用；main(argv) 与真实入口一致，普通命令无回归。
  - id: T4
    title: 联合契约样例与升级验收
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - tests/fixtures/observation_transport_contract.json
      - scripts/check_observation_reader.py
      - tests/test_observation_reader_contract.py
      - docs/AUTO_DESIGNER.md
      - docs/RELEASING.md
      - docs/cli.md
    scope: 提供稳定跨仓契约 fixture 与真实 prepare 检查入口，记录部署 reader 后启用 writer 的顺序及失败/回滚行为。
    acceptance: 固定 auto-designer producer 与本 reader 互通；live 仅合成探针，验证实际 scope/digest/只读文件，不把降级提示算通过。
---

# 0092 · 兼容 Gitea.com 的证据读取与能力声明

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

状态：用户已批准，T1–T4 已完成实现与验收。两仓改动属于配套候选，正式发行尚未执行；联合 release SHA 待读取端先合并后填写。

为 OpenAgents 的 issue 证据读取增加 ZIP 与 Gitea.com 签名附件下载，继续兼容自建 Gitea 的历史 gzip，并提供无副作用的读取能力命令。配套发布端为 auto-designer `0070-gitea-com-evidence-transport.md`。本组只扩展取证与启动诊断边界，不改变开发阶段、Issue 权限、历史文件解释或诊断补强回传语义。

## Motivation

目前 auto-designer 按 issue 授权构建 JSON，gzip 压缩后作为附件上传，并把 asset_id/sha256/bytes 写进 Issue 机器注释。OpenAgents 的下载器验证该 issue 附件成员后请求同源 UUID 地址；decode_package 校验摘要并固定 gzip 解压，再校验 issue、session、路径和 manifest。

2026-09-29 实测 Gitea.com 拒绝当前 gzip（422）、接受合法 ZIP（201），附件 303 跳到 R2 签名地址。旧下载器 NoRedirect 和旧 gzip-only 解析器分别阻断这两步。prepare 捕捉取证异常并在角色上下文保留“证据不可用”，因此“任务还能运行”不等于证据交接成功。

现有内部 Gitea 的 gzip 往返已经正常，应继续支持；新增 ZIP 不要求迁移旧 issue，也不让 reader 根据任意外链取证。

## Guide-level explanation

升级后的 OpenAgents 继续读取原自建实例的旧 gzip 附件与未声明编码的机器句柄。使用配套新版 auto-designer 的 Gitea.com 实验时，自动读取明确标记的 ZIP，向原有开发角色提供相同的版本匹配文件和 session 范围。

部署程序可在实际运行环境执行 `openagents observation-capabilities --json`，无需模型密钥、仓库配置或网络。它是只读机器接口，不初始化项目、不触发自动更新；普通 vigil/issue 命令行为保持原样。发布端只在需要 ZIP/R2 的新路径强制检查，旧 gzip 用户不需要额外配置。

新格式能力必须先部署到实际 executable/image，再启用发布端 ZIP；仅在开发机修改源码或检查版本号不能作为生产运行时已支持的证据。

## Reference-level explanation

### 两仓共同的传输契约（本段须保持一致）

- 内层 JSON 的 `format` 保持 `auto-designer:observation-evidence-v1`，issue、sessions、manifest、文件路径及摘要语义保持不变；不让 Agent 解析传输协议。
- Issue 机器句柄沿用 `asset_id/name/sha256/bytes`。旧 gzip 发布的句柄不新增字段；缺少 `encoding` 按 gzip。新增 ZIP 句柄必须带 `encoding: "zip"`；读取端也允许显式 `encoding: "gzip"`。未知值或声明与实际魔数不符必须拒绝，不自动猜测或回退。
- `sha256` 和 `bytes` 始终校验实际下载的压缩附件。传输上限 4,000,000 字节、解压后上限 24,000,000 字节；上限在真实读取过程中执行，不能只信服务器或 ZIP 元数据。
- ZIP 仅含一个普通文件 `evidence.json`，UTF-8、DEFLATE；拒绝额外或重复条目、目录、链接、加密和其他压缩算法。只在内存中有界读取该条目，不使用 extract/extractall。发布端固定条目时间戳为 1980-01-01 00:00:00、文件元数据及压缩级别 6，保证同一固定发布运行时重试得到相同字节；内部 JSON 序列化规则沿用原规则。
- `same-origin-v1` 保持现有自建 Gitea HTTP/HTTPS 直接 200 路径。新增 `gitea-com-r2-v1` 只适用于配置 origin 恰为 `https://gitea.com`、默认 443 且无子路径的实例；不得用后缀匹配放行伪装站点。
- 始终先从认证 Gitea API 验证附件属于当前 issue，再请求同源 `/attachments/{uuid}`，不采用正文外链或 `browser_download_url`。仅该已认证附件响应的 302/303/307/308 可进入一次受限跳转；目标必须为 HTTPS、默认 443、无 userinfo/fragment，hostname 精确满足 `^[a-f0-9]{32}\.r2\.cloudflarestorage\.com$` 的完整规则。其他存储域、IP 字面量、端口或二次跳转均拒绝。该边界是固定托管域名策略，依赖正常 DNS/TLS 与部署代理，不提供任意 URL 的通用下载能力。
- 对象存储使用新的无 Gitea Authorization、无 Cookie 请求，不继承 session 或 .netrc 认证；保留明确配置的网络代理。签名 query 仅用于本次请求，不写日志、异常正文或持久化状态。跨跳转共用单次附件下载 15 秒总预算，最终只接受 200，并继续验证字节数和摘要；API 请求仍禁止重定向。
- 能力命令为 `openagents observation-capabilities --json`，返回单个 JSON：`schema=openagents-observation-reader-capabilities-v1`、`marker=auto-designer:observation-evidence-v1`、`encodings=[gzip,zip]`、`zip_profile=single-evidence-json-v1`、`download_policies=[same-origin-v1,gitea-com-r2-v1]`、上述两项字节上限。调用不需要项目、凭证或网络，不自更新、不创建文件、不调用模型。
- 能力命令须在实际交付 executable/image 内执行；查询时设置已有开关 `OPENAGENTS_NO_SELF_UPDATE=1`，使尚不认识该命令的旧版本也不能先自更新。新路径的正式交付进程同样关闭运行期间自更新，记录实际 executable/image 身份。纯 gzip + same-origin 旧路径不强制要求新命令；ZIP 或 R2 路径能力缺失、未知、超时、预算不匹配均在派单/模型调用前明确阻断。

### 读取与角色交接

给 decode_package 增加默认 gzip 的可选编码参数，保持原调用有效。prepare 从机器句柄读 encoding，缺失走旧 gzip；下载长度/摘要校验先于解码。ZIP 取得原 JSON 后进入与 gzip 共用的 issue、session、路径、manifest、文件摘要校验，不复制第二套内容校验，也不依赖制品日志字段。

每次角色调用仍写入独立只读副本并保留授权 scope；旧 gap/outbox 的去重与授权保持不变。未知格式、下载拒绝或坏包继续采用既有“证据不可用”处理，不伪装成空日志或成功；错误中不暴露签名 URL。是否强制阻断整个开发阶段仍由既有机制决定，本组不增加新的通用交付门禁。需要新传输但运行时不支持的组合由发布端启动预检拦截。

下载扩展限定在 `utils.gitea.download_observation_asset`，不改变普通 REST `_http` 的策略。资产列表 API 保持原同源认证与有界读取，外部下载客户端不共享 Gitea 认证。测试直接检查实际发送的 headers、跳转次数和预算，而不是只检查配置中写了 allow_redirects=False。

### 能力命令与自更新边界

`openagents/observations/capabilities.py` 提供 stdlib-only 的 JSON 描述和 schema 常量。CLI 在 selfupdate.precheck、项目 resolve/init、forge 配置及任何网络操作前，对该命令精确早分发；同时在 argparse 中登记参数，保证帮助与补全不漂移。必须正确处理 `main(argv=...)` 和真实 sys.argv，参数错误只返回使用错误，不落入自更新。

所有已有普通命令的 selfupdate 顺序保持原状；能力命令新增用例断言 selfupdate、git、uv、forge、模型均未调用，并在空目录、无凭证、禁网环境得到单行有效 JSON，目录不产生新文件。发布端兼容旧版本查询时仍设置 OPENAGENTS_NO_SELF_UPDATE，防止未知命令先自更新。

能力字段描述的是本安装的 reader 实现；通过单测和跨仓测试把声明与真实 gzip/ZIP 解码、托管下载策略绑定，不能只有常量返回测试。预算或 profile 不符要让发布端拒绝新路径，不用版本字符串比较猜测能力。

### Task DAG 与文件分配

| Task | 职责 | 文件归属 | 依赖 |
|---|---|---|---|
| T1 | gzip/ZIP 双格式与句柄校验 | observations/evidence.py、现有证据测试 | 无 |
| T2 | 当前 issue 的受限 R2 下载 | utils/gitea.py、新传输测试 | 无 |
| T3 | 无副作用能力命令 | cli.py、新 capabilities.py、新能力测试、CLI 测试 | T1、T2 |
| T4 | 联合契约样例、端到端脚本与发布说明 | 新 contract fixture/跨仓脚本、AUTO_DESIGNER/RELEASING/CLI 文档 | T1、T2、T3 |

本仓不编辑 auto-designer 的代理配置或镜像 pin。配套仓负责两个代理模板的按需出口、容器公网地址、实际镜像构建、reader 预检和发布端 ZIP 选择；本仓输出可验证能力并提供读回脚本。发布顺序为本仓 reader → 实际部署能力验证 → auto-designer publisher，回滚 writer 到旧版前先检查站点是否支持 gzip；Gitea.com 不支持时停止新派单而不假装能回退。

### 验收和端到端入口

实现 `scripts/check_observation_reader.py`：默认离线，用契约 fixture 验证旧 gzip、显式 gzip、ZIP、编码声明错误、摘要、大小、issue、路径和恶意 ZIP。显式 live 模式可对测试用 issue 调用真实 prepare，要求 scope 包含授权 session、digest 正确、manifest/历史文件真实存在且只读；禁止把无异常返回或“证据不可用”的 context 当成功。

跨仓 fixture 包含旧句柄、带 encoding 的 ZIP 句柄与同一 JSON 的预期内容，以及拒绝用例的预期原因。配套 auto-designer 的跨仓脚本必须使用真实 build/publish/decode/prepare，不只比较常量；CI 可离线控制网络响应，真人探针再验证自建/Gitea.com 与实际容器/E2B。

重定向负例覆盖未经配置的站点、伪装 gitea.com、错误端口/userinfo、对象存储域欺骗、API 跳转、二次跳转、目标非 200、慢响应与超限，以及对象存储收到 Gitea token/cookie/netrc 认证的情况。ZIP 负例覆盖多文件、重复名、目录、链接、加密、非 DEFLATE、截断/CRC 错误及实际展开超限。原有跨 issue/摘要/路径/未授权补强负例继续有效。

### 2026-09-29 实际验收记录

- 本仓全量测试 1440 passed；最后增加 ZIP UTF-8 检查后，证据相关套件 58 passed；全仓 Ruff、spec validate/render/graph 和 diff check 通过。
- 固定候选 auto-designer 的真实 publisher 与本 reader，在宿主、Docker 容器及独立 E2B 中分别验证自建 Gitea 的 gzip/同源下载和 Gitea.com 的 ZIP/R2 签名下载。每个站点均通过真实 prepare 得到 authorized-session 的 7 个文件，内容、digest 与 0400 只读权限一致；没有调用模型。
- Docker 托管路径通过 internal 网络中的 Squid 验证 Gitea.com 和 R2 跳转；默认出口规则仍拒绝未启用的托管路径。E2B 仅使用独立短时探针 sandbox，结束后均已释放，未替换或修改正在运行的 N1 实验。
- 实际验收镜像为 `sha256:34a9bcafe9850fb9d8e8ee46cc9c93b09a1360c2bcf42f78a7eee3238b7fd271`，其构建时 OpenAgents 源树摘要为 `f8046d481e42448c0faea57704d6d62142fe00c52766fd6a768eeeff43f54325`。本段及派生索引是在构建后补写的验收元数据，运行时代码未变化；保留原构建记录，不将该摘要冒充补写后的整棵工作树摘要。
- 两仓属于配套候选；此处镜像是在提交前构建的，镜像与源树摘要是实际验证产物，不是正式发布 pin。release SHA 需等待 reader 先合并后按联合发布顺序更新。证据传输通过不代表五轮模型实验或完整新用户 Quick Start 均已完成。

## Drawbacks

双格式增加了一小段有界解码和测试维护工作，托管域策略也需要随着实际 Gitea.com 部署变化显式更新。保留对未知目标的拒绝会牺牲自动适应性，但避免将原受限取证入口变成任意网络下载器。

能力声明本身不能证明真实网络可达或凭证正确；同样，reader 的降级提示不能代替发布端启动失败和真人环境读回验收。

## Rationale and alternatives

在现有 evidence 和 Gitea driver 的独立边界扩展最小代码面，保持内层 JSON、原角色上下文和诊断回路。缺少 encoding 明确视为 gzip，避免旧句柄被新 sniff 规则改变解释。

只修改发布端无法解决旧 reader 的 gzip-only 和 NoRedirect；全部替换为 ZIP 会破坏旧自建组合；全局开放 urllib 重定向会影响普通 API 并可能携带认证。仅新增 python -m 能力模块虽然入口更小，但调用方容易使用另一 Python 环境；选择实际 openagents executable 的早分发命令，并针对自更新副作用验证。把两个仓的业务包互相 import 为运行时依赖会改变原 CLI/forge 边界，故仅在独立联合检查脚本中显式加载对端源码。

## Prior art

已有制品证据交接按当前 issue 授权、manifest 和摘要验证历史文件，并按调用隔离只读副本。相关 64 项基线测试及真实函数 gzip 联合检查已通过；同内容 ZIP 在旧 reader 下报 BadGzipFile。这些事实说明可复用内容校验，不证明新增 ZIP/R2 实现已完成。

[Gitea 配置文档](https://docs.gitea.com/1.22/administration/config-cheat-sheet/) 说明附件与签名存储行为；[Python zipfile](https://docs.python.org/3/library/zipfile.html) 和 [urllib.request](https://docs.python.org/3/library/urllib.request.html) 为有界解码及独立下载提供接口。站点支持范围以实际探针结果和本文件固定策略为准。

## Unresolved questions

用户已批准本文件的格式、下载边界、能力命令及先 reader 后 publisher 的顺序。兼容提交 SHA 和实际镜像摘要在联合验收后填写，不预造版本证据。

## Future possibilities

未来可增加经过独立评审的托管存储 profile；不在本组开放任意跨域地址。保持核心证据 envelope 不理解制品内部事件，未来更换 harness 的日志格式无需修改此传输层。
