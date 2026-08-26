# Device Test Lab｜分布式设备测试与用例资产平台

[English summary](#english-summary)

一个可自托管的测试控制平面，用于管理执行任务、协调桌面端和移动端 Agent，并承接 AI 生成用例的预览、发布与撤销。公开版本保留了可运行的调度和资产闭环，同时将公司数据库、认证和业务页面隔离在适配层之外。

## 工程实践界面

以下截图来自完整工程实践版本，用于展示平台化设计和端到端工作流。公开仓库现已提供同类信息架构的独立 Web 控制台，可直接体验概览、任务、设备、用例脑图/列表、发布预览与历史；企业认证、真实设备投屏等生产适配仍不包含在公开版本中。

### 在线测试用例资产

用例以模块和用例集管理，同时提供脑图、列表、节点编辑、标签、优先级、历史、导入导出和回收站能力。

![在线测试用例脑图](docs/assets/case-mindmap.png)

### 自动化任务与设备池

任务定义与每次执行记录分离；设备由 Agent 心跳上报，统一展示平台、系统、分组和可用状态。

<p>
  <img src="docs/assets/automation-tasks.png" alt="自动化任务管理" width="49%">
  <img src="docs/assets/device-inventory.png" alt="设备池" width="49%">
</p>

### 执行详情与测试报告

任务详情展示步骤结果和耗时；HTML 报告保留执行摘要、步骤截图及 Debug 证据。

<p>
  <img src="docs/assets/execution-detail.png" alt="自动化执行详情" width="49%">
  <img src="docs/assets/html-report.png" alt="带步骤截图的测试报告" width="49%">
</p>

### 远程设备控制

设备租约期间可查看实时画面并执行点击、长按、滑动、旋转、截图和应用管理操作。

![远程设备控制](docs/assets/remote-control.png)

## 当前已实现

### 分布式任务执行

- FastAPI 控制服务与可直接运行的 Web 控制台
- 概览、执行任务、设备资源、用例脑图/列表和发布记录页面
- 任务创建、查询、取消和结果回传
- Agent 主动领取任务，按平台能力匹配设备
- 基于 Lease 的占用、续租和超时恢复，避免 Agent 异常后任务永久卡死
- Agent 调用 `cross-platform-test-studio` 执行 Flow 并上传结果

### 测试用例资产

- 用例集列表与详情查询
- 发布前预览新增、重复和冲突
- 经确认后提交，使用 operation id 保证幂等
- 保存发布前状态并支持撤销
- 支持 AI Skill 通过通用 HTTP 协议发布完整用例集或选定功能分支
- Web 端可粘贴结构化用例树，预览新增、重复和冲突后确认发布

### 工程能力

- SQLite WAL 本地持久化
- Bearer Token 参考认证
- Dockerfile 与部署文档
- 调度、持久化、接口和用例发布测试

## 架构

```mermaid
flowchart TB
    A["Web 控制台 / API Client"] --> B["FastAPI 控制平面"]
    B --> C["任务服务"]
    B --> D["用例资产服务"]
    C --> E["Lease Scheduler"]
    E --> F[("SQLite WAL")]
    D --> G["Preview / Commit / Undo"]
    G --> F
    H["桌面端 / Android / iOS Agent"] -->|领取、续租、回传| C
    H --> I["Cross-platform Flow Runner"]
    I --> J["浏览器或测试设备"]
    K["AI Test Case Skill"] -->|发布草稿| D

    subgraph ProductionAdapters["生产环境可替换适配器"]
      L["Java 数据服务 / PostgreSQL / MySQL"]
      M["OIDC / 企业认证"]
      N["对象存储与可观测性"]
    end
    B -.-> M
    F -.-> L
    B -.-> N
```

## 快速开始

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
device-lab-api
```

打开 `http://127.0.0.1:8877`。公开版默认启用 Demo 模式，首次启动会写入三条待执行任务和一份 Notes 回归用例；设置 `DEVICE_LAB_DEMO=0` 可关闭示例数据。

进入“测试用例 → 导入用例”可以直接体验：

1. 新建用例集或选择已有用例集。
2. 粘贴 `quality-ai-skills` 生成的结构化用例树。
3. 预览新增、重复与冲突。
4. 无冲突时确认发布，并在发布记录中查看操作。

启动本地执行 Agent：

```bash
device-lab-agent \
  --device-id local-mac \
  --platform desktop \
  --studio-root ../cross-platform-test-studio
```

需要认证时，在 API 与 Agent 两侧配置相同的 `DEVICE_LAB_TOKEN`。

## 生产接入边界

当前实现可独立演示和二次开发，但以下能力属于扩展接口，不应误认为已经完整实现：

- PostgreSQL / MySQL 或既有 Java 数据服务适配器
- OIDC、企业单点登录和权限模型
- 大文件对象存储、视频录制及真实设备画面传输
- 面向大规模集群的多实例调度和可观测性

持久化和认证已与核心逻辑分离，生产接入时可以替换实现而不改变任务与用例发布协议。

## English summary

Device Test Lab is a self-hosted control plane for lease-based test execution and test-case publication. The public implementation includes FastAPI, SQLite WAL persistence, agent claiming and renewal, timeout recovery, cancellation, result reporting, and duplicate/conflict-aware preview, commit, and undo workflows.

## License

MIT
