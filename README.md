# 小票夹

**当前版本：v0.9.0a1**（阶段：**Reports / Goals / Chart UX 收口**；基线 = v0.8 Budget / 月度可花三端基线）

> 🚩 **v0.9.0a1 当前进度**：后端已加入服务端 Reports、Goals 和 Dashboard 卡片配置 API；Android 统计页接入真实报表、Goals 和 Dashboard 卡片设置，并按 ADR 引入 Vico 图表展示层；`/web` Reports 接入自托管 ECharts 且保留无 JS 回退；`/owner` 跟随三端设计 token 做视觉收口。v0.9 不改变账本核心闭环、身份契约或后端统计口径。

下一里程碑：进入 v1.0 后端数据能力地基，优先处理商品级小票、家庭拆账、10k CSV 导入和 v0.x -> v1.0 迁移 / 回滚工具。

小票夹是一个本地优先的私人半自动记账系统。账单和图片仍保存在 Windows 后端，v0.3 把旧 token/tenant 切换为账号、账本、设备和可撤销凭证；v0.4 落地多账本、Smart Ledger Engine、`/web` 和家庭账本基础；v0.5 收紧 `owner/member/viewer` 权限、成员审计、owner 转让、viewer 只读 UX 和三端角色词；v0.6-v0.7 完成固定支出、通知草稿、规则、标签和商家治理；v0.8 完成服务端预算和月度可花；v0.9 完成报表、Goals、Dashboard 卡片和图表 UX 收口。**当前身份契约仍保持 `identity_schema=v0.3` 不变。**

```text
iPhone UploadLink 或 Android 上传截图
  -> Windows FastAPI 后端按 ledger_id 保存图片和 pending 账单
  -> OCR / 分类 / 重复检测只生成草稿建议
  -> Android App 人工确认入账
  -> confirmed 账单同步到 Android Room 缓存
```

当前不做邮箱、手机号、密码、找回密码或商业云账号系统。Room 是 Android 本地缓存；卸载重装后通过新的 Pairing Code 重新绑定，再由 `syncConfirmed()` 从后端恢复已确认账单。

## 文档

文档按读者意图分组放在 docs/ 子目录下；完整索引见 [docs/README.md](docs/README.md)。这里只列常用入口。

### 核心架构

- [完整架构](docs/architecture/ARCHITECTURE.md)
- [项目结构](docs/architecture/PROJECT_STRUCTURE.md)
- [账号 / 账本 / 设备模型](docs/architecture/ACCOUNT_SYSTEM.md)
- [API 文档](docs/architecture/API.md)
- [安全说明](docs/architecture/SECURITY.md)
- [版本真值源](docs/architecture/VERSION.md)
- [数据保留与清理](docs/architecture/DATA_RETENTION.md)
- [Android 状态流](docs/architecture/ANDROID_STATE_FLOW.md)
- [Android 上传规格](docs/architecture/ANDROID_UPLOAD.md)
- [Android 外观 / 背景 / 沉浸模式](docs/architecture/ANDROID_APPEARANCE_BACKGROUND.md)

### 开发规范

- [工程规范](docs/rules/ENGINEERING_RULES.md)（单一权威来源，§14 含小票夹项目特定补充）
- [关键决策](docs/DECISIONS/)
- [官方资料与依赖来源](docs/rules/REFERENCES.md)
- [依赖管理](docs/rules/DEPENDENCIES.md)
- [错误码文案映射](docs/rules/ERROR_MESSAGE_MAPPING.md)

### 部署与运维

- [Bootstrap Owner](docs/runbook/BOOTSTRAP.md)
- [Cloudflare Tunnel 配置](docs/runbook/CLOUDFLARE_TUNNEL.md)
- [Windows 长期运行 Runbook](docs/runbook/WINDOWS_SERVICE_RUNBOOK.md)
- [Windows 备份任务](docs/runbook/WINDOWS_BACKUP_TASK.md)
- [实机联调 Runbook](docs/runbook/REAL_DEVICE_RUNBOOK.md)
- [Release 打包](docs/runbook/RELEASE_PACKAGING.md)
- [CI 说明](docs/runbook/CI.md)
- [灰度验收执行清单](docs/runbook/GRAY_ACCEPTANCE_EXECUTION.md)
- [版本回滚 Runbook](docs/runbook/ROLLBACK.md)
- [iPhone 快捷指令](docs/runbook/IOS_SHORTCUT.md)

### 产品规划

- [v0.5→v1.0 工程主控路线图](docs/roadmap/POST_BETA_DEVELOPMENT_ROADMAP.md)
- [能力路线图（Monarch 参照）](docs/roadmap/MONARCH_CAPABILITY_ROADMAP.md)
- [Monarch 设计参考边界](docs/roadmap/MONARCH_INSPIRED_UI.md)
- [三端信息架构](docs/roadmap/TRI_SURFACE_INFORMATION_ARCHITECTURE.md)
- [v0.9 设计包功能表](docs/current/V0_9_DESIGN_FUNCTION_TABLE.md)
- [v0.9 设计 Token 参考](docs/current/V0_9_DESIGN_TOKEN_REFERENCE.md)
- [第二版能力说明](docs/roadmap/V2_ROADMAP.md)

### 当前版本

- [CHANGELOG](docs/current/CHANGELOG.md)

### 设计参考

- [设计稿与主题缩略图](docs/design_reference/)（设计稿真值，新主题真值见 [V0_9_DESIGN_TOKEN_REFERENCE.md](docs/current/V0_9_DESIGN_TOKEN_REFERENCE.md)）

## 项目组成

```text
backend/   Windows 上运行的 FastAPI 后端
android/   Android App，Kotlin + Jetpack Compose
docs/      架构、API、安全、部署和后续规划文档
```

当前已经实现：

- `backend/`：FastAPI、SQLite、SQLAlchemy、账号/账本/设备身份表、Pairing Code、UploadLink、上传、账单、统计、受保护图片、缩略图、重复检测、分类规则、固定支出、标签、商家别名、服务端预算、Reports、Goals、Dashboard 卡片配置、服务器状态、可插拔 OCR 入口、图片清理维护接口，以及家庭成员审计 / owner 转让 / viewer 写保护。
- `android/`：灰度用户版和内部联调版、Pairing Code 绑定、Keystore session token、身份卡、指纹解锁、待确认、Android 上传截图、编辑、账本、手动记一笔、统计、报表图表、Goals、Dashboard 卡片设置、Room confirmed 缓存恢复、受保护图片预览、重复保留、OCR retry、CSV 导出、分类规则管理、家庭成员查看、邀请预览和只读 UX。
- `docs/`：v0.3 身份切换、v0.5 Household 模型、v0.8 预算路线、v0.9 Reports / Goals / Chart UX、架构、API、安全、工程规范、第二版路线和关键决策。

## 后端启动

```bat
cd /d E:\projects\xiaopiaojia\backend
setup.bat
run.bat
```

`setup.bat` 会创建 `.venv`、安装依赖，并在 `.env` 不存在时生成基础配置。v0.3 不再在 `.env` 里生成运行时 token。

## Owner Console（本机管理后台）

后端启动后在浏览器打开：

```
http://127.0.0.1:8000/owner
```

可中文查看服务状态、管理设备、生成 Android 绑定码、创建和管理 iPhone 上传链接，以及触发数据库手动备份。

Owner Console 仅允许本机访问（127.0.0.1），不通过 Cloudflare Tunnel 暴露到公网。

## 网页版账本（/web，本机）

v0.3.3 起，后端额外提供一个轻量网页版账本视图，方便在 PC 上确认 / 编辑账单：

```
http://127.0.0.1:8000/web
```

包括待确认列表、已确认列表（按月份过滤）、月度统计、单笔编辑 / 确认 / 拒绝。仅本机可访问，公网仍 403。

## 首次初始化 Owner 身份

```powershell
cd E:\projects\xiaopiaojia\backend
powershell -ExecutionPolicy Bypass -File scripts\bootstrap_owner.ps1
```

脚本会写入：

```text
backend\bootstrap\owner-bootstrap.txt
backend\bootstrap\owner-pairing.json
```

这些文件包含只显示一次的 admin token、iOS upload key 和 Android pairing code，已被 `.gitignore` 覆盖。

也可以调用 `POST /api/bootstrap/owner` 初始化，但该接口只接受后端本机 loopback 请求；公网请求会被拒绝。后端启动脚本默认关闭 Uvicorn access log，避免 UploadLink URL 中的 `upload_key` 被写入日志。

默认地址：

```text
http://127.0.0.1:8000
```

长期运行和开机自启使用根目录脚本：

```powershell
cd E:\projects\xiaopiaojia
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_windows_tasks.ps1
$env:TICKETBOX_SESSION_TOKEN="<session_token>"
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check_service_status.ps1 -Strict
```

手机离开家里 Wi-Fi 后仍然通过 Cloudflare Tunnel 访问公网域名，例如 `https://api.example.com`（请替换成你自己的私有域名）。必须保证 Windows 主机在线、没有睡眠，并且 FastAPI 后端和 cloudflared 正在运行。

## Android 打开

用 Android Studio 打开：

```text
E:\projects\xiaopiaojia\android
```

首次绑定输入账本地址和 6 位绑定码：

```text
https://api.我的域名.com
738294
```

绑定时 Android 会先用新 session token 完整执行 `syncConfirmed()` 并替换 Room confirmed 缓存，成功后再保存 session token、账号名、账本名、设备名、角色和绑定时间。

真机安装灰度 debug APK：

```powershell
cd E:\projects\xiaopiaojia\android
.\install_debug_apk.bat -Build -Launch
```

## iPhone 快捷指令

v0.3 推荐 iOS UploadLink，不再手填 `Upload-Token`：

```text
https://api.我的域名.com/u/<upload_key>?tz=Asia/Shanghai
```

快捷指令只需要分享图像、可选转换图像、获取 URL 内容、方法 POST、请求正文为文件。详见 [iPhone 快捷指令](docs/runbook/IOS_SHORTCUT.md)。

## 验证命令

后端：

```bat
cd /d E:\projects\xiaopiaojia\backend
.venv\Scripts\python.exe -m compileall app scripts tests
.venv\Scripts\ruff.exe check app scripts tests
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe scripts\smoke_test.py
```

Android：

```powershell
cd E:\projects\xiaopiaojia\android
$env:JAVA_HOME="$env:LOCALAPPDATA\Programs\Kimi\runtime"
$env:ANDROID_HOME=(Resolve-Path "..\.toolchains\android-sdk").Path
$env:PATH="$env:JAVA_HOME\bin;$env:ANDROID_HOME\platform-tools;$env:PATH"
.\gradlew.bat --no-daemon :app:testGrayDebugUnitTest
.\gradlew.bat --no-daemon :app:assembleGrayDebug :app:assembleInternalDebug
.\gradlew.bat --no-daemon :app:lintGrayDebug
```

全量：

```powershell
cd E:\projects\xiaopiaojia
powershell -ExecutionPolicy Bypass -File scripts\verify_project.ps1
git diff --check
powershell -ExecutionPolicy Bypass -File scripts\check_text_encoding.ps1
```
