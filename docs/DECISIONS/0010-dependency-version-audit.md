# 0010 依赖版本审计

## 决策

新增 `scripts/check_dependency_versions.ps1`，集中审计 Android 和后端依赖版本。

脚本默认只报告，不自动升级，也不因为发现新版直接失败。需要严格阻断时手动加 `-FailOnOutdated`。

## 原因

小票夹要求长期保持强依赖、弱耦合和可维护。依赖版本如果靠人工零散检查，后续很容易遗漏或引入预发布弱依赖。

Android 已经使用 Version Catalog，后端也使用固定 requirements，适合做集中审计。

## 规则

- Android 依赖从 `android/gradle/libs.versions.toml` 读取。
- 后端依赖从 `backend/requirements*.txt` 读取。
- 默认排除 alpha、beta、rc、snapshot、dev、eap、preview。
- 审计脚本只读，不修改项目文件。
- 依赖升级仍然需要人工评估 release notes 和运行完整验证。

## 后果

主线可以持续发现可升级依赖，但不会因为上游发布新版自动失败。

如果后续出现必须冻结的依赖，可以在文档中说明原因，而不是隐藏在业务代码里。
