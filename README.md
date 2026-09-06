# SublimeGit

一个面向 **vibe coding** 的 Sublime Text 4 极简 Git 插件：用原生 Text View +
Popup + 分栏拼出轻量 Git UI，替代 VS Code 的 Source Control 体验，但不背
Electron 的性能包袱。

覆盖三个核心场景：

1. **Git Panel** — 列出当前所有变更文件（staged / unstaged / untracked），
   光标所在行按 `⏎` 或双击，打开左右分栏 Diff（左 = 旧，右 = 新，增删改按
   色彩区分，自动适配当前 Color Scheme）。顶部有 **Push / Pull / Undo / Branch 按钮**，
   标题行标注 upstream 与 `↑ahead ↓behind`，未推送的本地提交列在 **OUTGOING**
   区块。
2. **Git Timeline 面板** — 整个仓库的提交历史，每行从左到右为
   hash / 作者 / 相对时间 / title（作者超宽截断为 `…`，各列定宽对齐）；提交行尾标注
   推送状态（`↑` = 还不在任何远程上，`(origin/main)` = 该提交是远程分支指向处）；
   鼠标悬停弹出完整提交信息（title / body / trailers footer / 作者 / 时间）；
   `⏎` 打开该提交变更文件列表，选择文件即查看该提交的 Diff。
3. **Git: File History** — `Cmd+Shift+P` 调出命令面板执行，用 quick panel 列出
   当前文件的提交历史（`git log --follow`，重命名可追踪），选择某条记录后以
   与 1 相同的左右分栏 Diff 展示。

## 安装

把本目录软链或复制到 Sublime Text 的 Packages 目录（macOS）：

```bash
ln -s "$(pwd)" "$HOME/Library/Application Support/Sublime Text/Packages/SublimeGit"
```

> 注意：**包根目录的 `.python-version` 文件（内容为 `3.8`）必须一起带上**——
> 它声明插件由 ST4 的 Python 3.8 宿主加载。若用复制方式安装，不要只拷 `.py`
> 文件；若控制台出现 `reloading python 3.3 plugin SublimeGit.*` +
> `SyntaxError: invalid syntax`，就是这个文件没到位。

要求 Sublime Text **Build 4050+**（默认 Python 3.8 插件宿主）与系统 `git`
（也可在设置里指定 `git_path`）。装好后重启 Sublime 或在 Console 里执行
`sublime.packages_path()` 确认路径即可。加载成功时 Console 应显示
`reloading python 3.8 plugin SublimeGit.plugin` 且无 Traceback。

## 使用

命令面板（`Cmd+Shift+P`）：

| 命令 | 作用 |
| --- | --- |
| `Git: Panel` | 打开/聚焦 Git Panel（变更文件 + 全部 Git 操作） |
| `Git: Open Timeline` | 打开/聚焦提交历史面板 |
| `Git: File History` | 当前文件历史（quick panel） |
| `Git: Stage Selected Files` | 暂存所勾选的文件（需光标在 Git Panel） |
| `Git: Unstage Selected Files` | 取消暂存所勾选的文件（需光标在 Git Panel） |
| `Git: Refresh Panel` | 刷新当前面板 |
| `Git: Push` | 推送当前分支（需光标在 Git Panel） |
| `Git: Undo Last Commit` | 撤销最新未推送提交（需光标在 Git Panel） |
| `Git: Pull (pull_mode: rebase / ff-only)` | 拉取当前分支（需光标在 Git Panel） |
| `Git: Switch Branch` | quick panel 选择并切换本地分支（需光标在 Git Panel） |
| `Git: Close Diff` | 关闭 Diff 分栏并恢复原布局 |

面板内快捷键（只在 SublimeGit 的面板里生效，不影响正常编辑）：

| 键 | 面板 | 作用 |
| --- | --- | --- |
| `⏎` / 双击 | Git Panel / Timeline | 打开光标所在项的 Diff / 提交 |
| `space` | Git Panel | 勾选 / 取消光标行的 checkbox；在根节点 `ALL` 行上 = 全选 / 反选全部 |
| `a` / `shift+a` | Git Panel | 全选 / 清空所有 checkbox |
| `shift+s` | Git Panel | 暂存所勾选的文件（只有 unstaged / untracked 行生效） |
| `s` | Git Panel | 取消暂存所勾选的文件（只有 STAGED 行生效） |
| `⌘⏎` / `ctrl+⏎` | Git Panel | 提交所勾选的文件（输入信息后回车） |
| `shift+p` | Git Panel | Push 当前分支（无 upstream 时自动 `-u` 到第一个 remote） |
| `p` | Git Panel | Pull 当前分支（默认 rebase，`pull_mode` 可改 ff-only） |
| `⌘⇧K` / `ctrl+⇧K` | Git Panel | Push（`shift+p` 的备选键位） |
| `⌘⌥P` / `ctrl+⌥P` | Git Panel | Pull（`p` 的备选键位） |
| `u` | Git Panel | 撤销最新未推送提交（soft reset，弹窗确认；已推送则拒绝） |
| `b` | Git Panel | quick panel 选择并切换本地分支（当前分支标 `*`，最近提交的排前面） |
| `r` | Git Panel / Timeline | 刷新 |
| `m` | Timeline | 加载下一页提交（默认 100/页） |
| `j` / `k` | Diff 视图 | 跳到下一个 / 上一个修改块 |
| `esc` | Diff 视图 | 关闭 Diff，恢复布局 |

快捷键思路与 yazi 一致：小写键做无副作用的操作（勾选、全选、pull 进来），
大写键做有副作用的操作（暂存、push 出去）；先 `space`/`a` 选中，再 `s`/`shift+s` 批量执行。

Diff 视图的颜色来自 color scheme 的 diff scopes
（`markup.inserted.diff` / `markup.deleted.diff` / `markup.changed.diff`），
Mariana、Monokai、Dracula 等常见主题天然支持，无需额外配色配置。
左右两栏滚动自动同步：两边按对齐后的 diff 行 1:1 对应，滚动任意一侧另一侧跟随
（Sublime 没有滚动事件，靠 diff 打开期间的轻量轮询实现，关掉 Diff 即停止）。
`j` 跳到下一个修改块、`k` 跳到上一个：以第一个可见行为基准（手动滚动后再按
也符合直觉），目标块首行滚到视口顶部并落下光标，两侧窗格一起跳；连续相邻的
增删改算同一个修改块，到头时状态栏提示。

### 交互式提交

Git Panel 是 yazi 风格的两步操作：先选中、再执行。列表顶部有一个根节点
`ALL (n/m)` 行——`space` 在它上面等于全选/反选全部文件（部分选中时显示半选
符号 `▣`），`a` / `shift+a` 随时全选 / 清空。勾选好后 `⌘⏎`（或 `ctrl+⏎`）
提交所勾选的文件，在弹出的输入面板里写 commit message 后回车。checkbox 只
表示「本次要操作的文件」，与 git 的 staged/unstaged 状态无关：

- 未暂存 / 未跟踪的所选文件按工作区内容 `git add -A --` 后进入提交；
- STAGED 分组的行按索引中已有的版本原样提交（不会额外带入工作区改动）；
- 注意：提交走的是完整 index commit，仓库里**已有暂存内容**的文件即使没勾选
  也会进入这次提交（它们在 STAGED 分组里可见，请留意）。

`shift+s` 暂存所勾选的文件（`git add -A --`，把工作区状态放进 index），
`s` 取消暂存所勾选的文件（`git reset HEAD --`，索引恢复到 HEAD）。两者都
只对匹配分组的行生效：staged 行在 `shift+s` 时被跳过（index 里已是用户
看到的版本，再 add 工作区副本可能带入未见改动），unstaged/untracked 行在
`s` 时被跳过——所以全选后按 `s` / `shift+s` 总是安全的，各分组各取所需。
只动 index、不碰工作区；重命名行自动带上新旧两个路径；操作后光标跟随文件
的新位置，且勾选状态跟着文件在两个分组之间迁移（选中集不因操作而散掉）。

这是插件的写操作路径之一，其余所有 git 调用保持只读。

### Push / Pull / Undo / Branch 与远程状态

Git Panel 顶部有 Push / Pull / Undo / Branch 四个按钮，点击或用快捷键
（`shift+p` / `p` / `u` / `b`）触发：

- **Push**：推送当前分支；分支还没有 upstream 时自动
  `git push -u <第一个 remote> <分支>` 建立关联。
- **Pull**：模式由设置项 `pull_mode` 决定，**默认 `"rebase"`**（即
  `git pull --rebase`，本地提交变基到远端之上）；改回 `"ff-only"` 则只做
  fast-forward，与上游分叉时直接报错。rebase 遇到冲突会停在中间态，面板横幅
  会提示去终端执行 `git rebase --continue` / `--abort`；插件从不主动发起 merge。
  Pull 按钮上会标注当前模式（Pull·rebase / Pull·ff-only）。
- **Undo**：撤销**最新一次未推送**的提交（`git reset --soft HEAD~1`），其改动
  原样回到 STAGED 列表，不丢内容，弹窗确认后执行。HEAD 已在远程时按钮置灰并
  拒绝执行——插件绝不改写已推送的历史（找回更早的本地提交请用 `git reflog`）。
  撤销仓库的第一个提交（无父提交）走 `update-ref -d HEAD`，分支回到「尚无提交」
  状态、改动保留。
- **Branch**：quick panel 列出所有本地分支（按最近提交时间排序，当前分支标
  `*`），回车即 `git checkout` 切换；选中当前分支等于无操作。切换会改动工作区
  与 index——若有未提交改动会被覆盖时 git 自行拒绝，拒绝原因照常显示在面板
  红色横幅里；插件从不加 `-f` 强切。远程分支的检出（如基于 `origin/foo` 建
  本地分支）仍需终端。
- 网络 git（push/pull）的超时独立于 `git_timeout`，由设置项
  `git_network_timeout` 控制（默认 120s）；凭据缺失时借助
  `GIT_TERMINAL_PROMPT=0` 快速失败并在状态栏给出可操作提示，不会卡住界面。

远程状态在两个面板中显式标注（数据来自本地缓存的 remote-tracking refs，
即最近一次 fetch 时的快照）：

- **Git Panel**：标题行显示 upstream 及 `↑ahead ↓behind`；存在未推送提交时，
  列表顶部出现 **OUTGOING** 区块，列出「不在任何 remote 上的提交」（最多 8 条，
  更多请去 Timeline），`⏎` 同样能打开该提交的变更文件列表。
- **Timeline 面板**：标题行显示 `↑N unpushed` 统计；每条提交行尾——`↑` 表示
  该提交还不在任何远程上，`(origin/main)` 标签表示该提交正是某个远程分支的
  指向处；hover popup 与状态栏 hint 同样标注。

「已在远程上」的判定是「可从任意 remote-tracking ref 可达」
（`git rev-list HEAD --not --remotes`），而不是只和 upstream 比：曾经推到
其他远程分支的提交不会被误标成未推送。

## 设计要点

```
SublimeGit/
├── plugin.py               # 入口：显式拉起各模块
├── commands.py             # 所有 sublime 命令类（薄壳）+ 渲染用 TextCommand
├── listeners.py            # 事件：激活刷新 / 悬停 popup / 双击
├── core/                   # 纯逻辑层（不 import sublime，可独立单测）
│   ├── git_runner.py       # subprocess 封装：list argv、worker 线程、超时
│   ├── repo.py             # Repository 门面 + 全部 git 输出解析器
│   ├── models.py           # GitFile / Commit / DiffContext
│   └── diff_engine.py      # difflib 双栏对齐（equal/replace/insert/delete）
├── views/                  # UI 层
│   ├── common.py           # 视图标记、状态注册表、repo 查找
│   ├── diff_view.py        # 统一 Diff 控制器（所有 Diff 走这一个入口）
│   ├── changes_panel.py    # 变更面板
│   ├── timeline_panel.py   # 时间线面板 + hover popup
│   └── file_history.py     # 文件历史 quick panel
└── tests/                  # python3 -m unittest discover -s tests
```

- **错误显示在面板内**：任何后台失败（刷新 / push / pull / commit）都会在面板
  内渲染红色错误横幅——一行可操作的简短提示 + git stderr 明细（最多 12 行），
  状态栏同步一行摘要；`r` 刷新成功后自动清除。排查细节才需要开控制台。
- **最小化写操作**：除交互式提交 / 批量暂存 / Push / Pull / Undo / 切换分支
  六个显式路径外，全部 git 调用均为只读，并设置 `GIT_OPTIONAL_LOCKS=0` 与
  `GIT_TERMINAL_PROMPT=0`（连 index 的可选锁都不碰，凭据缺失快速失败）；所有
  视图都是 scratch + read-only，绝不向工作区写任何临时文件。
- **命令类只放包顶层**：Sublime 只扫描包顶层 `.py` 文件来注册
  `sublime_plugin` 命令类；`core/`、`views/` 里的模块仅被 import，不会被
  扫描。命令类放子目录会静默失效（视图创建成功但永远渲染不出内容）。
- **全程异步**：git 子进程跑在 worker 线程，结果经 `sublime.set_timeout`
  回 UI 线程，大仓库不会卡界面。
- **统一 Diff 模型**：`DiffContext(left_spec, right_spec, path, …)` 用
  `"empty" | "index" | "worktree" | "<rev>"` 描述两侧，工作区 Diff
  （staged = HEAD↔INDEX，unstaged = INDEX↔WORKTREE）、提交 Diff
  （`sha^`↔`sha`）、文件历史 Diff 全部复用同一个渲染器。
- **解析器经过实测**（git 2.46）：`status --porcelain=v1 -z` 的重命名记录
  是「新路径 NUL 旧路径」，而 `diff --name-status -z` 相反是「旧 NUL 新」；
  `diff-tree -m` 会忽略 `--first-parent`（merge 需用 `git diff sha^ sha`）；
  `%b` 包含 trailers，需手动剥离才能分出 body 与 footer。这些都有回归测试。

## 测试

```bash
python3 -m unittest discover -s tests
```

## 已知边界（v1）

- 写操作仅限交互式提交、批量暂存/取消暂存（`shift+s` / `s`，作用于勾选集）、
  Undo、Push、Pull（`pull_mode`：默认 rebase，可选 ff-only）、切换本地分支
  （`b`）；fetch / merge / 手动 rebase 继续 / 新建与删除分支 / 检出远程分支
  仍需终端。
- 远程状态基于最近一次 fetch 的 remote-tracking refs 快照，不会自动 fetch。
- Timeline 为线性列表，未画分支 DAG 图。
- 超过 4000 行的 diff 跳过智能对齐，退化为逐行对比（避免 O(n²) 卡顿）。
- 每个 window 按「第一个 folder」识别仓库；多仓库工作区暂不区分。
