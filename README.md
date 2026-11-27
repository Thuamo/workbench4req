# 需求智能工作台

面向需求组、QA、开发组和审核组的中文 Web 工作台。团队可以在同一条需求下整理资料、跟踪澄清问题、编写和修订软件需求说明书（软需），再经人工会签发布到知识库。处理任务、文档版本、引用来源和审核意见均可从工作台追溯。

## 主要功能

| 模块 | 当前能力 |
| --- | --- |
| 需求与任务 | 通过向导登记业务需求并校验需求编号。按需求包管理澄清、软需和知识沉淀阶段的资料，发起处理任务，人工确认提取出的需求、澄清问题和关联候选。 |
| 软需生成与变更 | 根据选定资料和检索证据生成提纲与正文，支持人工确认提纲、保存草稿及恢复处理。需求变更可基于已有软需版本生成新版，或对受影响的段落提出局部修订建议。 |
| 文档编辑 | 富文本编辑支持表格、图片和批注。可查看来源、文档差异和编辑历史，由用户决定是否应用 AI 修改建议。支持 Word 导出及排版预览。 |
| 澄清台账 | 支持 Excel 增量导入预览、撤销导入批次、逐格编辑、修改历史、筛选、批量更新和导出。AI 可根据选定资料生成 24 列填报建议，经人工确认后写入台账。 |
| 知识库与会签 | 提供六类预置知识库，支持文件解析、原文预览、版本对比、索引和知识快照。支持批量送审与并行会签，全部通过后进入发布及索引流程。 |
| 知识问答 | 支持多轮流式回答、版本对比和影响分析。可按正式知识、本人已解析资料或选定文件检索，查看文档版本和引用原文。检索支持中文关键词与可选的向量模型。 |
| 技能与交付 | 支持通过 Slash 命令调用技能、导入导出技能包、管理版本和申请公共发布。内置任务包括需求解析、缺口识别、变更影响分析、软需质检、UML、思维导图和一页汇报 PPT。 |
| 权限与管理 | 支持需求组成员、QA、开发组成员、审核组成员和超级管理员五种角色。系统管理提供用户、角色、模型、审计和失败任务重试。 |

## 从登记需求到发布知识

1. 在**开启新工作 → 新建业务需求**中填写需求编号和背景，关联原始资料。
2. 在需求详情创建或选择需求包，选择资料并发起需求解析、澄清、影响分析或软需生成任务。
3. 在任务详情确认 AI 生成的候选。在文档编辑工作台修改正文、核对来源并确认版本。
4. 提交多人会签，在审核工作台查看决定和发布状态。索引就绪后，可在知识问答中使用已发布的版本。

## Windows 本地启动

准备 Python 3.12、Node.js 22 或更新版本，并确认 PowerShell 能调用 `python` 和 `npm.cmd`。在项目根目录执行以下命令。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.lock
npm.cmd --prefix frontend ci
npm.cmd --prefix frontend run build
.\start-local.cmd
```

首次启动时，脚本会在缺少 `.env` 的情况下生成 SQLite 配置和加密密钥，执行数据库迁移，并启动前端、API 和后台 Worker。停止和重启使用 `stop-local.cmd` 和 `restart-local.cmd`。

| 入口 | 地址 |
| --- | --- |
| 工作台 | [localhost:3000](http://localhost:3000) |
| 交互式 API 文档 | [127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) |
| API 健康检查 | [127.0.0.1:8000/health](http://127.0.0.1:8000/health) |

### 初始化管理员

服务首次启动后，在项目根目录执行以下命令。

```powershell
$env:PYTHONPATH = "$PWD/backend"
.\.venv\Scripts\python.exe -m app.cli init-admin --username workbench_admin
```

命令会交互设置密码。用户自行注册后默认加入需求组，超级管理员可在**系统管理**中分配其他角色。

### 配置模型和预览

- 在**系统管理**中添加并启用聊天模型，配置服务地址、模型名称和 API Key。AI 问答、提取与生成任务需要聊天模型，向量检索可另配嵌入模型。
- Word、PowerPoint 的部分预览和旧版 DOC 转换依赖本机 Office 或 LibreOffice。可通过 `CONVERTER_EXECUTABLE` 选择转换方式。
- UML 可下载 PlantUML 图源，思维导图可下载 Markdown 大纲。需要 SVG 预览或下载时，安装 Java 并在 `.env` 设置 `PLANTUML_JAR`。其他配置项见 [.env.example](.env.example)。

## 项目结构与检查

| 路径 | 内容 |
| --- | --- |
| `frontend/` | Next.js、React 与 TypeScript 前端。 |
| `backend/app/` | FastAPI 接口、LangGraph 工作流、文档检索和后台任务。 |
| `backend/migrations/` | Alembic 数据库迁移。 |
| `backend/tests/`、`scripts/` | 后端回归测试及本地启动、构建和验收工具。 |
| `compose.yaml` | PostgreSQL/pgvector 容器部署配置。 |

在项目根目录可运行 `.\scripts\run-tests.ps1` 执行后端测试，运行 `npm.cmd --prefix frontend run typecheck` 检查前端类型。

本地数据库、上传文件和工作流检查点保存在 `data/`。备份业务数据时一并保存原有 `.env`，其中的加密密钥用于读取已保存的模型 API Key。源码仓库保留配置模板 `.env.example`。
