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
python -m pytest
python scripts\smoke_test.py
```

后端 CI 会真实拉起 FastAPI smoke 服务，验证上传、鉴权、账单修改、确认、统计、CSV、图片保护、重复检测和维护接口。

同时会检查 `backend/scripts` 和 `android/scripts` 下的 PowerShell 脚本：

```text
UTF-8 with BOM
Windows PowerShell 语法
```

## Android Job

运行环境：

```text
ubuntu-latest
Temurin JDK 17
Android SDK platform 36
```

执行：

```bash
./gradlew --no-daemon :app:testDebugUnitTest
./gradlew --no-daemon :app:assembleDebug
./gradlew --no-daemon :app:lintDebug
```

成功后上传 artifact：

```text
ticketbox-debug-apk
```

保留 7 天。

## 安全边界

CI 不需要真实 Token。

不会上传：

```text
backend/.env
backend/data/*.db
backend/uploads/*
backend/backups/*.db
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
- Gradle 构建失败：先看 `:app:compileDebugKotlin` 或 `:app:kspDebugKotlin`。
- Lint 失败：看 `android/app/build/reports/lint-results-debug.html`。
