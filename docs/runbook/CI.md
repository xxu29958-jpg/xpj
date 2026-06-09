# CI 说明

仓库使用 GitHub Actions：

```text
.github/workflows/ci.yml
```

触发条件：

- push 到 `main`
- pull request 到 `main`

## 后端 Job

运行环境：

```text
windows-latest
Python 3.11
```

执行：

```powershell
python -m compileall app scripts tests
ruff check app scripts tests
python -m pytest --cov=app --cov-report=term-missing
python scripts\smoke_test.py
```

后端 CI 会输出 `app` 包覆盖率报告，并真实拉起 FastAPI smoke 服务，验证上传、鉴权、账单修改、确认、统计、CSV、图片保护、重复检测和维护接口。

同时会检查 `backend/scripts` 和 `android/scripts` 下的 PowerShell 脚本：

```text
UTF-8 with BOM
Windows PowerShell 语法
```

本地完整验证入口 `scripts\verify_project.ps1` 会先运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check_text_encoding.ps1
```

该检查会验证仓库文本文件可按 UTF-8 严格解码，并拦截常见 mojibake 片段，避免 Windows 默认编码把中文文案写坏。

## Android Job

运行环境：

```text
ubuntu-latest
Temurin JDK 21
Android SDK platform 36
```

执行：

```bash
./gradlew --no-daemon :app:testGrayDebugUnitTest
./gradlew --no-daemon :app:assembleGrayDebug :app:assembleInternalDebug
./gradlew --no-daemon :app:lintGrayDebug
```

成功后上传 artifact：

```text
ticketbox-gray-debug-apk
ticketbox-internal-debug-apk
```

保留 7 天。

CI 构建的 debug APK 必须使用仓库级稳定 debug 证书，避免每次 GitHub Actions runner 生成不同默认 debug key，导致真机无法覆盖升级安装。Android job 会在上传 artifact 前用 `apksigner verify --print-certs` 校验证书 SHA-256：

```text
91:15:22:41:7C:C5:01:6E:DA:DC:FF:AD:DE:7B:90:4D:92:8D:C4:2D:66:A7:97:84:44:45:AC:B5:BC:AE:10:6F
```

## 安全边界

CI 不需要真实 Token。

不会上传：

```text
backend/.env
backend/data/*
backend/uploads/*
backend/backups/*
android/app/build/*
```

这些文件由 `.gitignore` 排除。

## 常见失败点

后端：

- Python 依赖安装失败：检查 `backend/requirements*.txt`。
- `smoke_test.py` 失败：优先看具体 `OK ...` 停在哪一步。
- Windows PowerShell 脚本失败：确认 `.ps1` 仍是 UTF-8 with BOM。

Android：

- SDK 缺失：检查 workflow 的 `sdkmanager` 步骤。
- Gradle 构建失败：先看 `:app:compileGrayDebugKotlin`、`:app:kspGrayDebugKotlin` 或对应 internal 任务。
- Lint 失败：看 `android/app/build/reports/lint-results-grayDebug.html`。
# CI 与灰度版发布底线

灰度版实现期间，CI 仍然是合并和发布底线。任何账本隔离、Android 上传、UI 改造或 release 脚本变更，都不能绕过既有后端和 Android 验证。

灰度版新增要求：

- 后端测试必须覆盖账本隔离。
- Android 测试必须覆盖上传入口的非 UI 逻辑和 gray/internal 差异。
- PowerShell 脚本仍必须通过 UTF-8 with BOM 检查。
- GitHub 发布后必须等待 Actions 绿灯。
