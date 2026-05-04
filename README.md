# 小票夹

小票夹是一个私人半自动记账系统。第一版目标是跑通完整闭环：

```text
iPhone 截图账单
  -> iOS 快捷指令上传图片
  -> Windows FastAPI 后端保存截图并创建待确认账单
  -> Android App 拉取待确认账单
  -> 用户编辑金额、商家、分类、消费时间、备注
  -> 用户确认入账
  -> Android 本地 Room 缓存已确认账单
```

第一版不做真正 OCR、不做账号系统、不做多用户、不自动入账。AI/OCR 只作为第二版预留方向，任何账单都必须由用户确认后才正式入账。

## 文档

- [完整架构](docs/ARCHITECTURE.md)
- [API 文档](docs/API.md)
- [安全说明](docs/SECURITY.md)
- [iPhone 快捷指令](docs/IOS_SHORTCUT.md)
- [第二版路线](docs/V2_ROADMAP.md)
- [项目结构](docs/PROJECT_STRUCTURE.md)
- [CI 说明](docs/CI.md)
- [工程规范](docs/ENGINEERING_RULES.md)
- [后端开发规则](docs/BACKEND_RULES.md)
- [Android 开发规则](docs/ANDROID_RULES.md)
- [关键决策](docs/DECISIONS/)
- [官方资料与依赖来源](docs/REFERENCES.md)

## 项目组成

```text
backend/   Windows 上运行的 FastAPI 后端
android/   Android App，Kotlin + Jetpack Compose
docs/      架构、API、安全、部署和后续规划文档
```

当前已经实现：

- `backend/`：FastAPI、SQLite、SQLAlchemy、Token 校验、上传、账单、统计、受保护图片、缩略图、重复检测、分类规则、服务器状态、可插拔 OCR 入口和图片清理维护接口。
- `android/`：Android Studio 可打开的 Kotlin/Compose 工程，包含绑定服务器、指纹解锁、待确认、编辑、账本、统计、设置、Room、Retrofit、Keystore、BiometricPrompt、受保护图片预览、重复保留、OCR retry、CSV 导出和分类规则管理。
- `docs/`：架构、API、安全、工程规范、第二版路线和关键决策。

## 第一版优先级

1. 完成 FastAPI 后端：SQLite、Token 校验、上传截图、pending 记录、账单确认、拒绝、统计、受保护图片接口。
2. 完成 Android App 基础：绑定服务器、指纹登录、待确认列表、编辑页、账本页、本地 Room 缓存。
3. 补充运行说明：Windows 后端、Cloudflare Tunnel、iPhone 快捷指令、Android Studio。
4. 第二版再考虑 OCR、自动分类、重复截图检测、缩略图和图片生命周期。

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
.\gradlew.bat --no-daemon :app:testDebugUnitTest
.\gradlew.bat --no-daemon :app:assembleDebug
.\gradlew.bat --no-daemon :app:lintDebug
```
