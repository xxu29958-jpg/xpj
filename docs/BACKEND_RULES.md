# 后端开发规则

后端采用轻量分层：

```text
routes -> services -> database/models
```

## routes

职责：

- 接收 HTTP 请求。
- 校验 Token。
- 解析参数和请求体。
- 调用 service。
- 返回 Pydantic schema 或文件响应。
- 维护接口只能暴露窄动作，不能暴露任意文件路径参数。

禁止：

- 写复杂业务流程。
- 直接拼 SQL。
- 直接操作 Windows 真实路径。
- 返回原始 exception。
- 把 OCR、分类、重复检测、缩略图逻辑写死在 route。
- 做远程命令执行、远程关机、通用文件管理或目录浏览。

## services

职责：

- 文件保存和读取。
- pending 创建。
- 账单修改、确认、拒绝。
- 统计计算。
- OCR provider 调用。
- 分类规则匹配。
- 重复检测。
- 缩略图生成。
- 图片清理策略。

禁止：

- 依赖 FastAPI Request。
- 直接返回 HTTP Response。
- 硬编码 Token。
- 写 UI 文案。

## models

只定义 SQLAlchemy ORM 和索引。

禁止依赖 routes、schemas 或 HTTP 层。

## schemas

只定义 Pydantic 请求/响应模型和序列化规则。

禁止写数据库连接、业务流程和文件操作。

## 可插拔扩展点

这些功能只能通过 service/provider 扩展：

```text
OCR
自动分类
重复检测
缩略图
图片生命周期
生活化统计
```

第一版可以使用空实现或简单规则，但必须能替换。

OCR provider 当前约束：

- `empty` 是默认空实现。
- `mock` 只用于测试和联调。
- `rapidocr` 是本地图片 OCR provider。
- `local_llm` 是 OpenAI 兼容本地视觉模型 provider。
- OCR 只生成草稿建议，不自动确认入账。
- 上传后的自动 OCR 由 `OCR_AUTO_RUN` 控制，失败不得影响 pending 创建。
- 手动 OCR retry 可以把 provider 错误返回给 App。
- 规则抽取集中在 `receipt_parse_service.py`。

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
