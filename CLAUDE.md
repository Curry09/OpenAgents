## 总体原则：
这是一个RFC驱动的多Agent框架, 旨在解决如何从0开始快速搭建一个项目的需求。
需要最小化的搭建一个mvp,然后用这个mvp来迭代自身，因为自身就是一个产品。
交付程度以pr为单位，除了rfc设计环节，执行环节尽量少问，直到这个rfc做完并且pr的ci全通过了
商业上对标cursor、windsurf这类纯交互式agent场景
目标上，希望通过多agent协作，1、减少项目搭建的时间 2.来改变人类需要负责的部分（不再是细节，而是宏观把控）
后端兼容不同cli-agent，例如claude code, codex, nexau
需要整理成一个OpenAgents-cli。

## 设计理念：
1、遵循奥卡姆剃刀原则，如无必要，勿增实体，需要保证代码和架构的最小化、最简洁
2、每个Agent是去中心化的，在OpenAgents会维护每个Agent的状态，因此，在同一个项目里面，不同的Agent的背后接的coding agent可能不同，可以既有Claude code又有Codex等等,Agent之间的消息传递通过类似github的pr和comment机制，每次有一个新的comment,agent会收到一条消息，类似“your pr xxx has received a comment xxx”
4、Agent主要通过rfc来进行代码层面上的对齐，因此，每次改动都需要，先改rfc(标注状态为代码修改中)，再改代码，改完再更新rfc(标注状态为代码修改完毕)
5、对于openagents在正在写的某一个仓库，要做到能主动从仓库拉取issue,解决issue，提pr。pr需要人来审核,但是agent可以首先做comment。所以，有两个层面，一个是某一个feature的并行，一个是issue层面的并行，前者是用多agent，但是协同模式；后者是用
6、对于单个issue,派发一个agent去解决即可。
7、证据驱动，一切提到的概念等，都需要是有互联网来源的，需要真实查看来源具体内容，并且在对应位置给出引用。
8、以成果为中心，人不再做代码层面的测试，而是面向成果测试，因此，未来设计前端，主要视觉范围用于呈现成果，例如前端等等。
10、不同模块要解耦开


## 技术栈：
python

## 代码规范

- **提交信息**：遵循 Conventional Commits — `<类型>(<范围>): <描述>`
  - 类型：feat / fix / refactor / chore / docs / test / ci / style / perf / build
  - 范围：backend / cli / ci / deps / docs
- **代码检查**：Ruff（后端，行宽 100）
- **Git 钩子**：lefthook —— pre-commit（lint）+ commit-msg（commitlint）
- **Git 推送**：首次推送分支时使用 `git push -u origin <branch>` 设置 upstream tracking
- **代码注释**：每一层级都要引用对应的 RFC ID，详见 `.claude/skills/rfc-driven-development/references/code-comment-conventions.md`
- **语言**：代码注释中英文皆可，不强制区分，以清晰表达为先
- **Python 函数参数**：禁止位置参数（`/` 语法），private 函数（`_` 开头，不含 dunder）参数禁止默认值，调用方必须显式传参
