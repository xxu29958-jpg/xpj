# Android Release 发布包规格

日期：2026-05-09

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
- `server_url` — 构建期看到的 `TICKETBOX_SERVER_URL` 环境变量, 灰度验收脚本会跟 `-ServerUrl` 做 parity check(codex P1 #5)
- 构建 UTC 时间
- Git commit 信息

manifest 不写入 keystore、密码、服务器 token 或用户数据。

> Release build 默认拒绝 `https://api.example.com` placeholder: `assembleRelease` / `bundleRelease` 启动时如果 `TICKETBOX_SERVER_URL`(env)或 `local.properties` `ticketbox.serverUrl` 都没设, Gradle hook 会直接 fail 整个 task graph(`build.gradle.kts` 顶层 `gradle.taskGraph.whenReady`)。debug build 不受影响, 仍可用 placeholder 跑本机调试。

灰度验收脚本会校验 APK、SHA256 文件和 manifest 是否一致：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\accept_gray_release.ps1 -UseTemporaryKeystore
```

如果三者不一致，脚本会直接失败，不能把该包发给灰度用户。

## 9. RC artifact 门禁

从 PR artifact 发真机验收包时，不能只看 CI 通过或文件名。必须先运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify_rc_artifacts.ps1 `
  -RunId 25592323349 `
  -ExpectedCommit 67c05ee0ef4164fad2db1babfa27086cf5e00f73
```

脚本会自动下载 GitHub Actions artifact，并校验：

- CI run 已完成且结论为 success。
- CI run 的 commit 等于指定 commit。
- gray artifact 名称为 `ticketbox-gray-debug-apk`。
- internal artifact 名称为 `ticketbox-internal-debug-apk`。
- gray 包名为 `com.ticketbox`。
- internal 包名为 `com.ticketbox.internal`。
- gray/internal 包名必须不同。
- gray 版本名必须等于当前发布版本，例如 `0.9.0a1`。
- internal 版本名必须等于当前发布版本加 `-internal`，例如 `0.9.0a1-internal`。
- gray/internal 版本名必须不同。
- gray/internal `versionCode` 必须等于当前发布版本号约定，例如 `90000`。
- gray/internal APK 的 SHA256 必须分别记录，且不能相同。

脚本通过后会生成：

```text
artifacts/rc-gate/<run-id>/v0.9.0a1-artifact-manifest.json
artifacts/rc-gate/<run-id>/v0.9.0a1-handoff-checklist.md
```

manifest 记录：

- release candidate 名称。
- CI run id。
- CI commit。
- artifact 名称。
- APK 包名。
- versionName。
- versionCode。
- APK SHA256。
- APK 大小。

handoff checklist 必须写清楚：

- Android gray 用户只收到服务地址和一次性 Pairing Code。
- iPhone 快捷指令用户只收到对应 UploadLink URL。
- 服务拥有者才持有 internal APK、admin token 和维护凭据。
- 不得发出 `backend\.env`、admin token、session token、UploadLink、含凭证的日志/截图/CI 输出、keystore 或签名密码。

没有通过 `scripts\verify_rc_artifacts.ps1`，不得把任何包称为当前发布候选版本。
