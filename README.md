# 小票夹

小票夹是一个本地优先的私人半自动记账系统。账单和图片仍保存在 Windows 后端，v0.3 的核心变化是把旧 token/tenant 运行时模型切换为账号、账本、设备和可撤销凭证。

```text
iPhone UploadLink 或 Android 上传截图
  -> Windows FastAPI 后端按 ledger_id 保存图片和 pending 账单
  -> OCR / 分类 / 重复检测只生成草稿建议
  -> Android App 人工确认入账
  -> confirmed 账单同步到 Android Room 缓存
```

当前不做邮箱、手机号、密码、找回密码或商业云账号系统。Room 是 Android 本地缓存；卸载重装后通过新的 Pairing Code 重新绑定，再由 `syncConfirmed()` 从后端恢复已确认账单。

## 文档

- [账号 / 账本 / 设备模型](docs/ACCOUNT_SYSTEM.md)
- [Bootstrap Owner](docs/BOOTSTRAP.md)
- [回滚说明](docs/ROLLBACK.md)
- [完整架构](docs/ARCHITECTURE.md)
- [API 文档](docs/API.md)
- [安全说明](docs/SECURITY.md)
- [iPhone 快捷指令](docs/IOS_SHORTCUT.md)
- [Cloudflare Tunnel 配置](docs/CLOUDFLARE_TUNNEL.md)
- [Windows 长期运行 Runbook](docs/WINDOWS_SERVICE_RUNBOOK.md)
- [实机联调 Runbook](docs/REAL_DEVICE_RUNBOOK.md)
- [第二版路线](docs/V2_ROADMAP.md)
- [项目结构](docs/PROJECT_STRUCTURE.md)
- [CI 说明](docs/CI.md)
- [工程规范](docs/ENGINEERING_RULES.md)
- [后端开发规则](docs/BACKEND_RULES.md)
- [Android 开发规则](docs/ANDROID_RULES.md)
- [关键决策](docs/DECISIONS/)
- [官方资料与依赖来源](docs/REFERENCES.md)
- [依赖管理](docs/DEPENDENCIES.md)
- [灰度验收执行清单](docs/GRAY_ACCEPTANCE_EXECUTION.md)
- [错误码文案映射](docs/ERROR_MESSAGE_MAPPING.md)

## 项目组成

```text
backend/   Windows 上运行的 FastAPI 后端
android/   Android App，Kotlin + Jetpack Compose
docs/      架构、API、安全、部署和后续规划文档
```

当前已经实现：

- `backend/`：FastAPI、SQLite、SQLAlchemy、账号/账本/设备身份表、Pairing Code、UploadLink、上传、账单、统计、受保护图片、缩略图、重复检测、分类规则、服务器状态、可插拔 OCR 入口和图片清理维护接口。
- `android/`：灰度用户版和内部联调版、Pairing Code 绑定、Keystore session token、身份卡、指纹解锁、待确认、Android 上传截图、编辑、账本、手动记一笔、统计、设置、Room confirmed 缓存恢复、受保护图片预览、重复保留、OCR retry、CSV 导出和分类规则管理。
- `docs/`：v0.3 身份切换、架构、API、安全、工程规范、第二版路线和关键决策。

## 后端启动

```bat
cd /d E:\projects\xiaopiaojia\backend
setup.bat
run.bat
```

`setup.bat` 会创建 `.venv`、安装依赖，并在 `.env` 不存在时生成基础配置。v0.3 不再在 `.env` 里生成运行时 token。

首次初始化 owner 身份：

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

手机离开家里 Wi-Fi 后仍然通过 Cloudflare Tunnel 访问公网域名，例如 `https://api.zen70.cn`。必须保证 Windows 主机在线、没有睡眠，并且 FastAPI 后端和 cloudflared 正在运行。

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

快捷指令只需要分享图像、可选转换图像、获取 URL 内容、方法 POST、请求正文为文件。详见 [iPhone 快捷指令](docs/IOS_SHORTCUT.md)。

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
