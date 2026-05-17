# 后端开发规则

v0.3 后端必须遵守 `docs/ACCOUNT_SYSTEM.md`、`docs/API.md` 和 `docs/SECURITY.md`。所有账单、图片、统计、分类规则、重复检测、CSV 导出和 App 上传接口必须按 `ledger_id` 隔离；数据库字段名暂保留 `tenant_id` 时，其语义也必须是 `ledger_id`。不得用前端过滤代替后端隔离。

## 分层

后端采用 `routes -> services -> database/models` 三层架构。各层职责、禁止项和 schemas 规则详见 `docs/ENGINEERING_RULES.md` §3（后端分层）。

## 查询性能

- `confirmed` 分页、月份筛选、分类筛选必须在数据库层完成。
- 月度统计必须在数据库层聚合金额和数量，再在 service 层做分类归一。
- 常用筛选字段必须有 SQLite 索引迁移，包括 `status`、`category`、`expense_time`、`confirmed_at`、`image_hash`、`duplicate_status`。
- 不允许把已确认账单整表拉回 Python 后再分页。
- 不允许让上传、确认、同步这类主路径依赖未来才会运行的离线清理任务。

## 数据一致性与并发

- SQLite 运行连接必须开启 `PRAGMA foreign_keys=ON`；迁移旧库时先补齐复合外键需要的父表唯一索引，再更新父表数据。
- 带 `tenant_id` 的子表如果引用账单、标签、CSV 批次或规则应用批次，优先使用 `(id, tenant_id)` 复合外键；旧库无法完全依赖 FK 时，启动校验必须拦截跨账本遗留脏数据。
- `pending -> confirmed/rejected` 这类状态流转必须使用条件更新、租约或等价幂等机制，不能先读状态再无条件写回。
- 后台 OCR、CSV apply、规则批量 apply、通知草稿等异步/可重试路径必须处理陈旧写回、重复提交和并发 loser，不能覆盖用户之后的手动编辑。
- “同账本、同月份、同分类/总支出只能有一个启用目标”这类产品语义必须同时有 service 层校验和数据库级唯一护栏。

## OCR provider 约束

- `empty` 是默认空实现。
- `mock` 只用于测试和联调。
- `rapidocr` 是本地图片 OCR provider。
- `local_llm` 是 OpenAI 兼容本地视觉模型 provider。
- OCR 只生成草稿建议，不自动确认入账。
- 上传后的自动 OCR 由 `OCR_AUTO_RUN` 控制，失败不得影响 pending 创建。
- 手动 OCR retry 可以把 provider 错误返回给 App。
- 规则抽取入口集中在 `receipt_parse_service.py`，金额、商家、时间、分类候选逻辑分别放在 `receipt_parse_amount.py`、`receipt_parse_merchant.py`、`receipt_parse_time.py`、`receipt_parse_category.py`。

## 验收

后端改动完成后至少运行：

```bat
cd /d E:\projects\xiaopiaojia\backend
.venv\Scripts\python.exe -m compileall app scripts
.venv\Scripts\ruff.exe check app scripts
.venv\Scripts\python.exe scripts\smoke_test.py
```

## Windows 脚本编码

`backend/scripts/*.ps1` 必须能被 Windows PowerShell 5.1 直接执行。

规则：

- 使用 UTF-8 with BOM 保存包含中文输出的 `.ps1`。
- `.bat` 入口使用 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File ...`。
- 不要求用户安装 PowerShell 7、WSL 或容器。
- 修改脚本后必须实际运行一次，不只做静态语法检查。
