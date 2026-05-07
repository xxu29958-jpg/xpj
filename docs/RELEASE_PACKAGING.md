# Android Release 发布包规格

日期：2026-05-05

## 1. 目标

灰度测试不能只发 debug APK。需要提供可重复构建的 release APK 流程。

## 2. Release 要求

Release 版本必须满足：

- 使用 release 签名。
- keystore 不进 Git。
- 密码不进 Git。
- 不打印网络调试日志。
- 不暴露 token。
- 不展示开发诊断入口。
- 不默认展示服务器域名。
- 可安装到真机。

## 3. 环境变量

构建 release APK 前设置：

```powershell
$env:TICKETBOX_KEYSTORE_PATH="E:\secrets\ticketbox-release.jks"
$env:TICKETBOX_KEY_ALIAS="ticketbox"
$env:TICKETBOX_KEYSTORE_PASSWORD="..."
$env:TICKETBOX_KEY_PASSWORD="..."
```

脚本不得输出密码。

## 4. 构建脚本

新增脚本：

```text
scripts/build_release_apk.ps1
```

职责：

- 检查 Android 工程存在。
- 检查 keystore 环境变量。
- 检查 keystore 文件存在。
- 调用 Gradle 构建 release APK。
- 输出 APK 路径和版本号。
- 不打印密钥和密码。

输出：

```text
android/app/build/outputs/apk/gray/release/app-gray-release.apk
```

内部版输出：

```powershell
.\scripts\build_release_apk.ps1 -Flavor internal
```

```text
android/app/build/outputs/apk/internal/release/app-internal-release.apk
```

## 5. Gradle 配置

`android/app/build.gradle.kts` 需要：

- 从环境变量读取 signing config。
- `gray` 和 `internal` flavor 分开。
- debug 和 release buildType 分开。
- `gray` 不显示开发诊断入口。
- `internal` 保留内部联调入口。
- versionCode 和 versionName 明确管理。

## 6. 安装说明

文档需要说明：

- debug APK 用于开发联调。
- `grayRelease` APK 用于灰度安装。
- `internalDebug/internalRelease` 用于服务拥有者联调。
- release 包需要签名环境变量。
- keystore 丢失后同一应用无法平滑升级。

## 7. 验收

必须验证：

```powershell
.\scripts\build_release_apk.ps1
```

成功后：

- APK 文件存在。
- 真机可安装。
- release 版不显示普通用户不该看到的诊断入口。
- CI 不需要真实 keystore；CI 只检查脚本语法和 debug 构建。

本机完整灰度验收可以使用临时 keystore 验证 release 构建链路：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\accept_gray_release.ps1 -UseTemporaryKeystore
```

临时 keystore 只用于本机验收，不能发给灰度用户。

## 8. 发布产物校验

`scripts/build_release_apk.ps1` 构建成功后会同时输出三类文件：

```text
android/app/build/outputs/apk/gray/release/app-gray-release.apk
android/app/build/outputs/apk/gray/release/app-gray-release.apk.sha256
android/app/build/outputs/apk/gray/release/app-gray-release.manifest.json
```

`sha256` 文件用于校验 APK 是否被传错或损坏。

`manifest.json` 记录：

- flavor
- build type
- versionName
- versionCode
- APK 文件名
- APK 大小
- SHA256
- 构建 UTC 时间
- Git commit 信息

manifest 不写入 keystore、密码、服务器 token 或用户数据。

灰度验收脚本会校验 APK、SHA256 文件和 manifest 是否一致：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\accept_gray_release.ps1 -UseTemporaryKeystore
```

如果三者不一致，脚本会直接失败，不能把该包发给灰度用户。
