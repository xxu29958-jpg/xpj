# 小票夹 Android

Android Studio 工程目录。当前使用 Kotlin、Jetpack Compose、Material 3、Room、Retrofit、BiometricPrompt 和 Android Keystore。

## 本机要求

- Android Studio。
- JDK 17。
- Android SDK Platform 36，与项目 `compileSdk` 对应。
- Gradle 由 Android Studio/Wrapper 管理。

## 打开方式

1. 用 Android Studio 打开 `E:\projects\xiaopiaojia\android`。
2. 等待 Gradle Sync 完成。
3. 运行 `app`。

如果使用模拟器连接 Windows 本机后端，可以把服务器地址配置为：

```text
http://10.0.2.2:8000
```

正式使用建议配置 Cloudflare Tunnel 的 HTTPS 域名。

## 命令行构建

本项目已生成 Gradle Wrapper。

如果机器已经安装 JDK 17+ 和 Android SDK，可以运行：

```powershell
cd E:\projects\xiaopiaojia\android
.\gradlew.bat :app:assembleDebug
```

当前这台机器也准备了项目本地工具链：

```text
E:\projects\xiaopiaojia\.toolchains\gradle\gradle-8.13
E:\projects\xiaopiaojia\.toolchains\android-sdk
```

Wrapper 当前使用 Gradle 8.14.4。首次运行会下载对应 Gradle 发行包。本地工具链构建命令：

```powershell
$env:JAVA_HOME="$env:LOCALAPPDATA\Programs\Kimi\runtime"
$env:ANDROID_HOME=(Resolve-Path "..\.toolchains\android-sdk").Path
$env:PATH="$env:JAVA_HOME\bin;$env:ANDROID_HOME\platform-tools;$env:PATH"
.\gradlew.bat --no-daemon :app:assembleDebug
```

本地单元测试：

```powershell
$env:JAVA_HOME="$env:LOCALAPPDATA\Programs\Kimi\runtime"
$env:ANDROID_HOME=(Resolve-Path "..\.toolchains\android-sdk").Path
$env:PATH="$env:JAVA_HOME\bin;$env:ANDROID_HOME\platform-tools;$env:PATH"
.\gradlew.bat --no-daemon :app:testDebugUnitTest
```

Lint：

```powershell
$env:JAVA_HOME="$env:LOCALAPPDATA\Programs\Kimi\runtime"
$env:ANDROID_HOME=(Resolve-Path "..\.toolchains\android-sdk").Path
$env:PATH="$env:JAVA_HOME\bin;$env:ANDROID_HOME\platform-tools;$env:PATH"
.\gradlew.bat --no-daemon :app:lintDebug
```

APK 输出位置：

```text
android\app\build\outputs\apk\debug\app-debug.apk
```

## 真机安装

手机准备：

1. 打开开发者选项。
2. 打开 USB 调试。
3. 用数据线连接 Windows。
4. 手机上允许这台电脑调试。

安装已有 debug APK：

```powershell
cd E:\projects\xiaopiaojia\android
.\install_debug_apk.bat
```

构建并安装：

```powershell
.\install_debug_apk.bat -Build
```

安装后启动：

```powershell
.\install_debug_apk.bat -Launch
```

多台设备同时连接时先列出设备：

```powershell
.\install_debug_apk.bat -ListDevices
```

再指定设备：

```powershell
.\install_debug_apk.bat -Serial 设备序列号
```

## USB 反向转发联调

真机正式使用建议走 Cloudflare HTTPS 域名。如果手机上的 VPN、代理或 fake-ip DNS 导致 HTTPS 握手失败，可以先用 USB 反向转发验证 App 和 Windows 后端闭环：

```powershell
$adb = "E:\projects\xiaopiaojia\.toolchains\android-sdk\platform-tools\adb.exe"
& $adb -s 设备序列号 reverse tcp:8000 tcp:8000
```

debug APK 支持仅联调用的 intent 绑定入口：

```powershell
cd E:\projects\xiaopiaojia\android
.\install_debug_apk.bat -Build -ReverseBackend -ClearData -DebugBind
```

等价的底层 adb 命令：

```powershell
$envLines = [System.IO.File]::ReadAllLines("E:\projects\xiaopiaojia\backend\.env", [System.Text.UTF8Encoding]::new($false))
$appToken = (($envLines | Where-Object { $_ -match "^APP_TOKEN=" }) -replace "^APP_TOKEN=", "").Trim()
& $adb -s 设备序列号 shell am start -n com.ticketbox/.MainActivity `
  --es ticketbox.debug.server_url "http://127.0.0.1:8000" `
  --es ticketbox.debug.app_token $appToken
```

该入口只在 debuggable APK 中生效，不进入 release 构建。正式绑定仍然使用 App 页面输入服务器地址和 `APP_TOKEN`。

安装后首次打开 App：

1. 绑定服务器地址。
2. 输入 `APP_TOKEN`。
3. 进入设置页。
4. 点击“联调自检”。

自检会检查 Token、服务器状态、pending、confirmed 分页、统计、分类、月份、重复检测和受保护图片接口。

完整端到端实机流程见：

```text
docs\REAL_DEVICE_RUNBOOK.md
```

## 数据同步规则

- 远端金额字段是 `amount_cents`，本地字段是 `amountCents`，单位都是分。
- Room 的 `serverId` 有唯一索引。
- confirmed 同步时按 `serverId` 显式查询并更新，不重复插入。
- 服务器不可用时，账本页显示 Room 本地 confirmed 缓存。
- 每次 confirmed 同步成功后记录本机上次同步时间；清除本地缓存会同时清除该状态。

## 已接入功能

- 绑定服务器使用 `/api/auth/check`。
- 待确认页加载 pending 账单和受保护缩略图。
- 编辑页可查看缩略图/原图、保存、确认、删除、OCR retry、标记“仍然保留”。
- 账本页同步 confirmed 并写入 Room。
- 账本页支持月份、分类和商家/备注/标签搜索，并显示当前筛选合计和上次同步时间。
- 账本页支持手动记一笔，保存后直接进入已确认账本。
- 账本页支持编辑已确认账单，保存后同步更新本地 Room。
- 编辑页和账本页支持后端分类快捷选择。
- 账本页和统计页支持后端月份快捷选择。
- 统计页显示月统计和生活化统计，并支持月份切换。
- 设置页可切换松雾、柚光、港湾、莓果 4 套皮肤。
- 设置页可测试连接、运行联调自检、查看服务器状态、重新同步、清缓存、清绑定、添加/编辑/启停/删除分类规则。
- 账本页支持通过系统文件选择器导出 CSV，不需要存储权限。

## 安全规则

- 首次绑定使用 `GET /api/auth/check` 校验 Token。
- APP_TOKEN 存入 Android Keystore。
- 生物识别只用于本地解锁，不替代后端 Bearer Token。
- OkHttp 日志不得打印 Header、Body 或 Token。
