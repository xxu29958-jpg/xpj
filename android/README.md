# 小票夹 Android

Android Studio 工程目录。当前使用 Kotlin、Jetpack Compose、Material 3、Room、Retrofit、BiometricPrompt、Android Keystore 和系统 Photo Picker。

项目按受众拆成两个 flavor：

```text
gray      灰度用户版，包名 com.ticketbox
internal  内部联调版，包名 com.ticketbox.internal
```

灰度用户版默认不显示服务器域名、Token、Cloudflare、端口、日志、接口名或诊断入口。内部联调版才保留连接诊断和调试入口。

## 本机要求

- Android Studio。
- JDK 17。
- Android SDK Platform 36。
- Gradle Wrapper 由仓库管理。

## Android Studio 打开

1. 用 Android Studio 打开 `E:\projects\xiaopiaojia\android`。
2. 等待 Gradle Sync 完成。
3. 运行 `app`，优先选择 `grayDebug`。

真机正式使用建议绑定 Cloudflare Tunnel HTTPS 域名。模拟器访问 Windows 本机后端时可使用：

```text
http://10.0.2.2:8000
```

## 命令行构建

```powershell
cd E:\projects\xiaopiaojia\android
$env:JAVA_HOME="C:\Program Files\Eclipse Adoptium\jdk-17.0.19.10-hotspot"
$env:Path="$env:JAVA_HOME\bin;$env:Path"
.\gradlew.bat --no-daemon :app:testGrayDebugUnitTest
.\gradlew.bat --no-daemon :app:assembleGrayDebug :app:assembleInternalDebug
.\gradlew.bat --no-daemon :app:lintGrayDebug
```

输出：

```text
android\app\build\outputs\apk\gray\debug\app-gray-debug.apk
android\app\build\outputs\apk\internal\debug\app-internal-debug.apk
```

项目级完整验证：

```powershell
cd E:\projects\xiaopiaojia
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify_project.ps1
```

## 真机安装

手机准备：

1. 打开开发者选项。
2. 打开 USB 调试。
3. 用数据线连接 Windows。
4. 手机上允许这台电脑调试。

列出设备：

```powershell
cd E:\projects\xiaopiaojia\android
.\install_debug_apk.bat -ListDevices
```

构建、安装并启动灰度用户版：

```powershell
.\install_debug_apk.bat -Flavor gray -Build -Launch -Serial 设备序列号
```

构建、安装并启动内部联调版：

```powershell
.\install_debug_apk.bat -Flavor internal -Build -Launch -Serial 设备序列号
```

内部联调版可通过 USB 反向转发和 debug intent 快速绑定本机服务：

```powershell
.\install_debug_apk.bat -Flavor internal -Build -ReverseBackend -ClearData -DebugBind -Serial 设备序列号
```

说明：

- `DebugBind` 只允许 internal 版使用。
- 灰度用户版必须走正常绑定流程，不暴露内部联调入口。
- 绑定页使用后端生成的 6 位 Pairing Code。绑定成功后，App 把 session token 保存到 Android Keystore，并保存账号、账本、设备和角色信息。

## Android 自带上传

灰度用户版在“待确认账单”页提供“上传截图”主按钮：

1. 点击“上传截图”。
2. 系统 Photo Picker 打开。
3. 选择账单截图。
4. App 以 multipart/form-data 上传，字段名为 `file`。
5. 请求头使用 `Authorization: Bearer <session_token>`。
6. 上传成功后自动刷新待确认列表。

Android 不保存、不发送 iPhone 快捷指令使用的 UploadLink。

## Release APK

Release 需要外部 keystore，密钥和密码不进 Git：

```powershell
$env:TICKETBOX_KEYSTORE_PATH="E:\secrets\ticketbox-release.jks"
$env:TICKETBOX_KEY_ALIAS="ticketbox"
$env:TICKETBOX_KEYSTORE_PASSWORD="..."
$env:TICKETBOX_KEY_PASSWORD="..."
cd E:\projects\xiaopiaojia
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_release_apk.ps1 -Flavor gray
```

输出：

```text
android\app\build\outputs\apk\gray\release\app-gray-release.apk
```

内部版：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_release_apk.ps1 -Flavor internal
```

## 已接入功能

- 首次绑定使用 Pairing Code 调用 `/api/auth/pair`，成功后用 `/api/auth/check` 校验 session token。
- 待确认页加载 pending 账单和受保护缩略图。
- 待确认页支持 Android Photo Picker 上传截图。
- 编辑页可查看截图、保存草稿、确认入账、忽略这张、重试识别、标记“仍然保留”。
- 账本页同步 confirmed 并写入 Room，离线时显示本地缓存。
- 账本页支持月份底部弹窗、分类标签筛选、搜索、导出 CSV、手动记一笔和编辑已入账账单。
- 统计页显示总支出、账单数量、分类占比、最近 7 天、最大一笔和高频商家。
- 设置页灰度用户版只显示账本状态、同步状态、外观、数据与安全和关于。
- 设置页内部版显示连接诊断和高级工具。
- Room schema 导出在 `app/schemas/`。

## 安全规则

- session token 不写死、不打印、不明文存 SharedPreferences，只保存到 Android Keystore。
- 生物识别只用于本地解锁，不替代后端 Bearer Token。
- OkHttp 日志不得打印 Header、Body 或 Token。
- 灰度用户版不展示服务器域名、Token、接口名、Cloudflare、端口、日志或诊断脚本。
