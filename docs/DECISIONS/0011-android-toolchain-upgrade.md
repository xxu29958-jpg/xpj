# 0011 Android 构建工具链升级

## 决策

Android 构建工具链升级为：

- Android Gradle Plugin `9.2.0`
- Gradle Wrapper `9.4.1`
- Kotlin Compose compiler plugin `2.3.21`
- KSP Gradle Plugin `2.3.7`

## 原因

依赖审计脚本查到这些插件已有稳定版。小票夹要求避免过时库和弱依赖，构建工具链也必须纳入依赖治理，而不是只审业务库。

AGP `9.2.0` 官方文档要求 Gradle `9.4.1`，所以 AGP 和 Gradle 必须整组升级。

AGP 9 内置 Android Kotlin 支持，因此不再显式应用 `org.jetbrains.kotlin.android` 插件。

## 约束

- 继续使用 Java 17 编译目标。
- 继续使用 Android SDK 36。
- 不引入 alpha、beta、rc 插件。
- 升级必须通过 `:app:testDebugUnitTest`、`:app:assembleDebug`、`:app:lintDebug` 和 CI。

## 后果

Android Studio 打开项目时会使用更新的 Gradle/AGP/Kotlin/KSP 组合。

如果后续 Room、KSP 或 Compose 编译出现兼容性问题，先按同组依赖检查，不做单点盲目降级。
