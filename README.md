# SublimeGit

一个面向 **vibe coding** 的 Sublime Text 4 极简 Git 插件：用原生 Text View +
Popup + 分栏拼出轻量 Git UI，替代 VS Code 的 Source Control 体验，但不背
Electron 的性能包袱。

覆盖三个核心场景：

1. **Git Changes 面板** — 列出当前所有变更文件（staged / unstaged / untracked），
   光标所在行按 `⏎` 或双击，打开左右分栏 Diff（左 = 旧，右 = 新，增删改按
   色彩区分，自动适配当前 Color Scheme）。
2. **Git Timeline 面板** — 整个仓库的提交历史，列表只显示 title；鼠标悬停弹出
   完整提交信息（title / body / trailers footer / 作者 / 时间）；`⏎` 打开该提交
   变更文件列表，选择文件即查看该提交的 Diff。
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
| `Git: Open Changes` | 打开/聚焦变更文件面板 |
| `Git: Open Timeline` | 打开/聚焦提交历史面板 |
| `Git: File History` | 当前文件历史（quick panel） |
| `Git: Refresh Panel` | 刷新当前面板 |
| `Git: Close Diff` | 关闭 Diff 分栏并恢复原布局 |

面板内快捷键（只在 SublimeGit 的面板里生效，不影响正常编辑）：

| 键 | 面板 | 作用 |
| --- | --- | --- |
| `⏎` / 双击 | Changes / Timeline | 打开光标所在项的 Diff / 提交 |
| `space` | Changes | 勾选 / 取消光标行的 checkbox |
| `a` | Changes | 全选 / 清空所有 checkbox |
| `⌘⏎` / `ctrl+⏎` | Changes | 提交所勾选的文件（输入信息后回车） |
| `r` | Changes / Timeline | 刷新 |
| `m` | Timeline | 加载下一页提交（默认 100/页） |
| `esc` | Diff 视图 | 关闭 Diff，恢复布局 |

Diff 视图的颜色来自 color scheme 的 diff scopes
（`markup.inserted.diff` / `markup.deleted.diff` / `markup.changed.diff`），
Mariana、Monokai、Dracula 等常见主题天然支持，无需额外配色配置。
左右两栏滚动自动同步：两边按对齐后的 diff 行 1:1 对应，滚动任意一侧另一侧跟随
（Sublime 没有滚动事件，靠 diff 打开期间的轻量轮询实现，关掉 Diff 即停止）。

### 交互式提交

Changes 面板每个文件行前有 checkbox：`space` 勾选/取消，`a` 全选/清空，
`⌘⏎`（或 `ctrl+⏎`）提交所勾选的文件，在弹出的输入面板里写 commit message 后回车。
checkbox 只表示「本次要操作的文件」，与 git 的 staged/unstaged 状态无关：

- 未暂存 / 未跟踪的所选文件按工作区内容 `git add -A --` 后进入提交；
- STAGED 分组的行按索引中已有的版本原样提交（不会额外带入工作区改动）；
- 注意：提交走的是完整 index commit，仓库里**已有暂存内容**的文件即使没勾选
  也会进入这次提交（它们在 STAGED 分组里可见，请留意）。

这是插件唯一的写操作路径，其余所有 git 调用保持只读。

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

- **保护工作目录**：全部 git 调用均为只读，并设置 `GIT_OPTIONAL_LOCKS=0`
  （连 index 的可选锁都不碰）；所有视图都是 scratch + read-only，绝不向
  工作区写任何临时文件。
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

- 只读浏览，不提供 stage / commit / push 等写操作（后续可加）。
- Timeline 为线性列表，未画分支 DAG 图。
- 超过 4000 行的 diff 跳过智能对齐，退化为逐行对比（避免 O(n²) 卡顿）。
- 每个 window 按「第一个 folder」识别仓库；多仓库工作区暂不区分。
