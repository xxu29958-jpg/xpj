# 0009 Android 依赖使用 Version Catalog

日期：2026-05-05

## 背景

Android 工程已经接入 Compose、Room、Retrofit、OkHttp、Moshi、BiometricPrompt、KSP 等依赖。如果版本散写在多个 `build.gradle.kts` 文件里，后续升级、审计和排查兼容性问题都会变难。

## 决策

Android 插件和库版本统一维护在：

```text
android/gradle/libs.versions.toml
```

根工程使用 `libs.plugins.*` 引用插件，App 模块使用 `libs.*` 引用依赖。

## 约束

- 模块 `build.gradle.kts` 不再散写第三方库版本号。
- 新增依赖必须先进入 Version Catalog。
- 不引入 alpha、beta、停止维护或来源不清的依赖进入主线。
- 依赖调整后必须通过 Android 单元测试、debug 构建和 lint。

## 影响

后续升级 AndroidX、Compose、Room、Retrofit、OkHttp 等依赖时只改一处。CI 和本机验证仍按既有流程执行。
