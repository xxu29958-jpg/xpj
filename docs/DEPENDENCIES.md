# 依赖管理

小票夹依赖策略是“稳定、可维护、可复现”，不要为了追新引入 alpha、beta、rc、next、canary 或来源不明的库。

## 基本规则

- 后端 Python 依赖固定在 `backend/requirements.txt` 和 `backend/requirements-dev.txt`。
- Android 依赖版本集中在 `android/gradle/libs.versions.toml`。
- 不在业务模块里散写第三方版本号。
- 默认使用稳定版；预发布版本必须有明确理由，并写入 ADR。
- 新增库前先确认维护状态、许可证、平台兼容性和必要性。
- 依赖升级必须跑完整验证，不能只改版本号。

## 审计脚本

运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check_dependency_versions.ps1
```

默认行为：

- 读取 Android Version Catalog。
- 查询 Android 库、Gradle 插件在 Google Maven 和 Maven Central 的 `maven-metadata.xml`。
- 读取后端 requirements。
- 查询 PyPI JSON API。
- 排除 alpha、beta、rc、snapshot、dev、eap、preview、next、canary 等预发布版本。
- 只报告结果，不自动升级。

如果需要让落后依赖直接失败：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check_dependency_versions.ps1 -FailOnOutdated
```

## 升级流程

1. 先运行依赖审计脚本。
2. 查对应库的官方 release notes。
3. 只升级一组相关依赖，例如 AndroidX 一组、Room 一组、后端 FastAPI 一组。
4. 更新锁定版本或 Version Catalog。
5. 跑：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify_project.ps1
```

6. 如果涉及数据模型、Room、API 行为或安全边界，补文档和 ADR。

## CI 策略

CI 执行依赖审计脚本，但默认不因为“发现新稳定版本”失败。原因是上游发布新版本不应该让主线突然红掉。

真正升级依赖时，必须在本地和 CI 都跑完整验证。
