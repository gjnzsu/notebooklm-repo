# Obsidian 与 NotebookLM 桥接方案

这个仓库现在提供一个轻量桥接脚本：以 Obsidian vault 作为长期知识库，按文件夹或标签选择 Markdown 笔记，上传到指定 NotebookLM notebook 做分析、问答和生成。

## 推荐工作流

1. Obsidian 是主库：原始摘录、永久笔记、主题索引都留在 vault。
2. NotebookLM 是分析工作台：按主题上传一批笔记、文章或资料，生成总结、FAQ、思维导图、播客或报告。
3. 回流到 Obsidian：把 NotebookLM 产出的结论整理成 `Literature Notes`、`Permanent Notes` 或 `MOC`，不要把整段生成内容无筛选地倒回主库。

## 首次同步

先 dry-run，看会上传哪些笔记：

```powershell
.\scripts\Sync-ObsidianToNotebookLM.ps1 `
  -Vault "D:\Obsidian\MyVault" `
  -NotebookTitle "AI Product Management" `
  -IncludeDir "Areas\AI" `
  -IncludeTag "notebooklm"
```

确认后执行上传：

```powershell
.\scripts\Sync-ObsidianToNotebookLM.ps1 `
  -Vault "D:\Obsidian\MyVault" `
  -NotebookTitle "AI Product Management" `
  -IncludeDir "Areas\AI" `
  -IncludeTag "notebooklm" `
  -Execute
```

同步状态会写入当前目录的 `.notebooklm-obsidian-sync.json`。默认不会修改你的 Obsidian 笔记。

## 筛选方式

按文件夹：

```powershell
-IncludeDir "Areas\Physics"
```

按标签：

```powershell
-IncludeTag "notebooklm"
```

排除文件夹或标签：

```powershell
-ExcludeDir "Archive" -ExcludeTag "private"
```

强制重新上传：

```powershell
-Force -Execute
```

## 建议的 Obsidian 结构

```text
Inbox/
Sources/
Literature Notes/
Permanent Notes/
MOC/
Projects/
```

推荐只把 `Sources/`、`Literature Notes/` 或某个项目文件夹中带 `#notebooklm` 的笔记同步到 NotebookLM。`Permanent Notes/` 更适合作为沉淀后的主库，不建议频繁全量上传。

## 回流模板

把 NotebookLM 生成的关键结论回写到 Obsidian 时，可以用这个 frontmatter：

```markdown
---
type: notebooklm-output
source_notebook: AI Product Management
created: 2026-06-10
tags:
  - notebooklm/output
---

# 主题标题

## 核心结论

## 支撑材料

## 可行动问题

## 需要回查的来源
```

## 下一步可以自动化的部分

后续可以继续加：

1. 从 NotebookLM `ask` 自动生成固定问题清单并保存为 Obsidian Markdown。
2. 从 NotebookLM `history` 或 `note list/get` 拉取结果，自动放入 vault 的 `NotebookLM Outputs/`。
3. 做 Windows 计划任务，每天同步带 `#notebooklm` 的新增笔记。
