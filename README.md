# 小票夹

小票夹是一个私人半自动记账系统。当前灰度基线是跑通完整闭环：

```text
iPhone 快捷指令或 Android 上传截图
  -> Windows FastAPI 后端按 token 级租户隔离保存图片
  -> 可插拔 OCR 草稿识别管线按配置生成金额、商家、时间、分类建议
  -> 后端创建待确认账单
  -> Android App 拉取待确认账单
  -> 用户编辑金额、商家、分类、消费时间、备注
  -> 用户确认入账
  -> Android 本地 Room 缓存已确认账单
```

当前不做账号注册/登录系统，不做商业云账号体系，不自动入账。OCR 是可插拔草稿识别管线，只生成待确认草稿和建议；多租户是 token 级灰度隔离，不是账号系统。任何账单都必须由用户确认后才正式入账。

## 文档

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

- `backend/`：FastAPI、SQLite、SQLAlchemy、Token 校验、上传、账单、统计、受保护图片、缩略图、重复检测、分类规则、服务器状态、可插拔 OCR 入口和图片清理维护接口。
- `android/`：Android Studio 可打开的 Kotlin/Compose 工程，包含灰度用户版和内部联调版、绑定账本、指纹解锁、待确认、Android 上传截图、编辑、账本、手动记一笔、统计、设置、Room、Retrofit、Keystore、BiometricPrompt、受保护图片预览、重复保留、OCR retry、CSV 导出和分类规则管理。内部版保留连接诊断，灰度用户版不显示开发面板。
- `docs/`：架构、API、安全、工程规范、第二版路线和关键决策。

## 当前基线

1. FastAPI 后端：SQLite、Token 校验、token 级灰度隔离、上传截图、pending 记录、账单确认、拒绝、统计、导出、受保护图片和缩略图接口。
2. 识别与辅助录入：可插拔 OCR 草稿识别管线、分类规则、重复检测、图片生命周期维护；这些能力只辅助用户确认，不替用户入账。
3. Android App：绑定服务器、指纹登录、待确认列表、Android 上传截图、编辑页、账本页、统计页、设置页、本地 Room 缓存、灰度用户版和内部联调版。
4. 运行说明：Windows 后端、Cloudflare Tunnel、iPhone 快捷指令、Android Studio、真机联调和 CI。

## 后端启动

```bat
cd /d E:\projects\xiaopiaojia\backend
setup.bat
run.bat
```

`setup.bat` 会创建 `.venv`、安装依赖，并在 `.env` 不存在时生成随机 Token。已有 `.env` 时不会覆盖。

默认地址：

```text
http://127.0.0.1:8000
```

长期运行和开机自启使用根目录脚本：

```powershell
cd E:\projects\xiaopiaojia
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_windows_tasks.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check_service_status.ps1 -Strict
```

手机离开家里 Wi-Fi 后仍然通过 Cloudflare Tunnel 访问 `https://api.zen70.cn`，不要求和电脑在同一个局域网里。必须保证 Windows 主机在线、没有睡眠，并且 FastAPI 后端和 cloudflared 正在运行。详细流程见 [Windows 长期运行 Runbook](docs/WINDOWS_SERVICE_RUNBOOK.md)。

## Android 打开

用 Android Studio 打开：

```text
E:\projects\xiaopiaojia\android
```

首次绑定服务器时使用：

```text
https://api.我的域名.com
```

开发模拟器连接本机后端可以使用：

```text
http://10.0.2.2:8000
```

真机安装灰度 debug APK：

```powershell
cd E:\projects\xiaopiaojia\android
.\install_debug_apk.bat -Build -Launch
```

实机联调预检：

```powershell
cd E:\projects\xiaopiaojia
powershell -ExecutionPolicy Bypass -File scripts\real_device_preflight.ps1 -SkipDevice
```

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

一键跑完整本地验证：

```powershell
cd E:\projects\xiaopiaojia
powershell -ExecutionPolicy Bypass -File scripts\verify_project.ps1
```

检查中文文本编码：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check_text_encoding.ps1
```

检查 Cloudflare Tunnel 公网入口：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check_cloudflare_endpoint.ps1 `
  -ServerUrl https://api.你的域名.com
```

电脑端一键诊断：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\diagnose_ticketbox.ps1 -Strict
```
