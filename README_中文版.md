# SkillScope V4 — GitHub Pages 全自动采集版

这是为现有网站 `https://ffd1992zw-cmyk.github.io/ai-/` 制作的升级包。保留 V3 约140条预置资源与个人收藏/隐藏功能，并添加公开技能目录的后台自动增量采集。

## 新增什么

- **自动采集**：GitHub Actions 每小时第17分钟（UTC；也就是北京时间同样每小时第17分钟）尝试执行一次，可能因平台拥堵延迟，不保证秒级实时。
- **新项目发现**：扫描 Anthropic、OpenAI Plugins、Vercel-Labs、Microsoft 等5个代码仓库，识别 `SKILL.md` 及插件清单。
- **提取可核查信息**：优先从源文件的 `name`、`description` 提取说明，记录原始路径及对应版本；无法核实时保留待审核说明。
- **去重与限量**：每轮最多加入35项；保留已收录条目，自动去重、按7大关注领域初筛。
- **自动发布**：采集后主动执行 GitHub Pages 部署，不依赖机器人提交再触发新部署。
- **同一公开目录**：手机与电脑访问同一个网站时，看到共同的自动采集目录；**收藏、隐藏、个人编辑依然仅在本地浏览器保存**。

## 汉化版 GitHub 上线步骤（一次性）

你的仓库：`https://github.com/ffd1992zw-cmyk/ai-`

1. 在“代码”页点击 **添加文件 → 上传文件**，上传本包根目录的 `index.html`，覆盖原文件，提交到 `main` 主分支。
2. 在“代码”页点击 **添加文件 → 创建新文件**，文件名填 `scripts/collect.py`，把本包同名文件全文粘贴，提交到 `main`。（如果你熟悉 Git，也可以批量推送，省去粘贴。）
3. 同样创建 `.github/workflows/skillscope-sync.yml`，把本包同名文件全文粘贴后提交。**注意文件名里 `workflows` 要带 s，扩展名是 `.yml`。**
4. （可选）创建 `data/catalog.json` 并复制本包内容；不创建也没关系，第一次成功执行会自动生成。
5. 进入 **设置 → 页面（Pages）→ 构建和部署 → 来源**，选择 **GitHub Actions**，而非“从分支进行部署”。
6. 进入 **设置 → 操作（Actions）→ 常规（General）→ 工作流权限（Workflow permissions）**，确保仓库允许工作流写入仓库内容。该工作流显式声明 `contents:write`，若 GitHub 权限策略阻止仍需在仓库设置放行。
7. 打开 **操作（Actions）**，左侧选择 **SkillScope 自动情报采集与发布** → **运行工作流程（Run workflow）** → 选择 `main` → 运行。等待出现绿色对勾。
8. 打开 `https://ffd1992zw-cmyk.github.io/ai-/`，强制刷新。在“数据管理与同步”中查看后台最近采集时间与新增条目数。

### 特别提醒

GitHub 官方规定，通过 Actions 内置 `GITHUB_TOKEN` 的 `git push` 不会再次触发“从分支部署”的 Pages 重建，所以第5步 **切换为 GitHub Actions** 是必需的，本包会在同一次工作流里主动发布。仅上传 `index.html` 不会启动后台采集。

## 出错时怎么判断

| 情况 | 排查点 |
|---|---|
| 没有出现工作流 | 检查 `.github/workflows/skillscope-sync.yml` 文件路径和 YAML 完整性 |
| `Resource not accessible by integration` / 403 | 检查仓库 Actions 工作流权限，确保允许 `contents:write` |
| Pages 部署失败 | 检查 Pages 来源是否已切换为 GitHub Actions，Actions 部署步骤中的错误日志 |
| 发现数量为0 | 查看 Actions 日志中的 `source_success` 与 `errors`，确认 GitHub API 可访问及是否存在匹配目录 |
| 网站显示“云端未启用” | 先确认 `data/catalog.json` 在主分支里存在且 `last_checked` 非空，再确认 Actions 已发布成功 |
| 个人收藏不同步 | 属于当前设计：云端同步公开资源目录，本地偏好不会上传，不是故障 |

## 安全与边界

- 公开目录中的条目默认是“待审核”，**不是安装成功或安全认证**。
- 不安装、执行或加载第三方 Skill 内的脚本；只从 GitHub API 读取元信息与描述。
- 不需要自购服务器，也不需要在网页里暴露 GitHub Token。GitHub Actions 使用其内置令牌。
- 本版没有 AI 自动撰写深度测评、自动测试每个技能或个人账户收藏云同步；每周 ChatGPT 情报任务也未直接写入 JSON。
- GitHub 定时任务可能延迟，公开仓库长期无活动时定时任务可能被平台停用；以 Actions 页面为准。

## 文件说明

- `index.html`：V4 前端，兼容 V3 本地收藏。
- `scripts/collect.py`：仅使用 Python 标准库的采集程序。
- `.github/workflows/skillscope-sync.yml`：定时扫描、提交 JSON 和主动发布 Pages 的完整工作流。
- `data/catalog.json`：自动生成的共享资源目录，包中仅附初始化占位文件。
- `.nojekyll`：静态文件标识，保留。
- `tests/test_collect.py`：可离线运行的采集代码测试。

测试：`python -m unittest discover -s tests -v`。
