# 小票夹

小票夹是一个**本地优先、由 Owner 管理的家庭财务事实系统**。

账务事实、身份、离线意图和收据附件保存在受管 Windows 安装中；iPhone UploadLink、Android、浏览器账本和 Desktop Manager 通过受约束能力访问。OCR、分类和外部模型只生成建议，最终入账与更正由用户确认。

```text
iPhone UploadLink / Android 上传
              ↓
Windows FastAPI + PostgreSQL + 附件存储
              ↓
pending 草稿与 OCR/分类建议
              ↓
用户在 Android / Web 等受权界面确认
              ↓
服务端财务事实 + 可重建的客户端投影
```

## 稳定边界

- 主数据不托管到商业云；远程访问只改变网络路径，不改变数据权威。
- Windows 是当前正式宿主，不依赖 Docker、WSL 或 Linux shell。
- PostgreSQL 与附件共同构成服务端持久事实；Android Room 和前端缓存是可重建投影。
- Account、Ledger、Device、Token、UploadLink、Pairing 等身份与能力由后端裁决。
- `/owner` 是本机管理面；公网 `/web`、UploadLink 与 API 只开放明确 allowlist，并执行对应鉴权。
- OCR、分类和 AI 不得自动覆盖用户确认过的财务事实。
- 安装、升级、修复、备份、恢复、保留数据重装和卸载不得静默切换 DataRoot、installation identity 或服务身份。

具体实现、已完成门和在途工作以**当前 exact HEAD、PR、任务合同、测试与运行证据**为准，不在 README 复制易过期进度表。

## 仓库组成

| 路径 | 责任 |
|---|---|
| `backend/` | FastAPI、领域服务、PostgreSQL、Web/Owner 页面和共享静态资产 |
| `android/` | Kotlin + Jetpack Compose 客户端与 Room 投影 |
| `desktop/` | Windows Desktop Manager 与用户侧管理能力 |
| `distribution/` | Windows 安装、升级、修复、卸载和发布适配 |
| `infra/` | 受控基础设施配置 |
| `scripts/` | 仓库级验证与操作脚本 |
| `docs/` | 架构、runbook、工程细则、路线和决策历史 |

## 开始工作

1. 先读 [`AGENTS.md`](AGENTS.md)：它是 Codex、Claude Code 和开发者唯一默认加载的施工合同。
2. 再按当前责任使用 [`docs/README.md`](docs/README.md) 定位需要的架构、runbook、专题规则或 ADR。
3. 修改前确认分支/worktree、exact HEAD 和工作区状态；不要从 README 猜当前阶段。
4. 验证强度按风险和任务退出门决定，不机械执行所有历史清单。

Claude Code 通过 [`CLAUDE.md`](CLAUDE.md) 导入同一份 `AGENTS.md`，不维护第二套规则。

## 常用权威入口

### 当前契约

- [仓库工作合同](AGENTS.md)
- [文档导览](docs/README.md)
- [系统架构](docs/architecture/ARCHITECTURE.md)
- [项目结构](docs/architecture/PROJECT_STRUCTURE.md)
- [API 契约](docs/architecture/API.md)
- [身份模型](docs/architecture/ACCOUNT_SYSTEM.md)
- [安全边界](docs/architecture/SECURITY.md)
- [版本真值源](docs/architecture/VERSION.md)

### 工程与验证

- [工程细则](docs/rules/ENGINEERING_RULES.md) — 按责任读取，不是第二套常驻合同
- [代码质量门](docs/rules/CODE_QUALITY_STANDARDS.md)
- [依赖治理](docs/rules/DEPENDENCIES.md)
- [错误码与用户文案](docs/rules/ERROR_MESSAGE_MAPPING.md)
- [CI 说明](docs/runbook/CI.md)
- [发布打包](docs/runbook/RELEASE_PACKAGING.md)

### Windows 生命周期与运行

- [Windows 长期运行](docs/runbook/WINDOWS_SERVICE_RUNBOOK.md)
- [备份任务](docs/runbook/WINDOWS_BACKUP_TASK.md)
- [回滚](docs/runbook/ROLLBACK.md)
- [实机联调](docs/runbook/REAL_DEVICE_RUNBOOK.md)
- [`distribution/`](distribution/)
- [`desktop/`](desktop/)

### 决策历史

- [ADR 人读索引](docs/DECISIONS/README.md)
- [ADR 契约标准](docs/rules/ADR_CONTRACT_STANDARD.md) — 仅在修改 ADR 或治理工具时读取

ADR 记录长期决定及其理由，不自动证明当前实现符合。生成的 ADR registry、状态表和依赖图只对文件中标注的 review base 有效；基线早于当前 HEAD 时只能用来检索，必须用当前代码、测试和运行事实复核。

## 产品原则

**界面可以变化，财务事实、身份、用户意图和恢复能力不能失真。**

产品化不是把后台换一层皮，而是让真实能力在 Android、Web、Owner 和 Desktop 上更容易使用，同时保留权限、离线、冲突、错误和恢复语义。
