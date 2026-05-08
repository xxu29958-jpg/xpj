# 实机联调 Runbook

本文档用于小米 15 Pro 到手后做端到端联调。目标是确认：

```text
iPhone 快捷指令上传截图
  -> Cloudflare Tunnel
  -> Windows FastAPI 后端
  -> Android App 待确认
  -> 编辑金额和分类
  -> 确认入账
  -> Room 本地缓存和统计可见
```

联调过程不打印 Token，不公开 `uploads/`，不开放路由器端口，不把后端改成监听 `0.0.0.0`。

## 1. Windows 后端

初始化：

```bat
cd /d E:\projects\xiaopiaojia\backend
setup.bat -Dev
```

启动：

```bat
run.bat
```

默认监听：

```text
http://127.0.0.1:8000
```

本地验证：

```powershell
cd E:\projects\xiaopiaojia
powershell -ExecutionPolicy Bypass -File scripts\verify_project.ps1
```

如果只验证后端：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\verify_project.ps1 -SkipAndroid
```

## 2. Cloudflare Tunnel

Cloudflare Tunnel 只转发本机服务：

```text
api.你的域名.com -> http://127.0.0.1:8000
```

详细配置见：

```text
docs\CLOUDFLARE_TUNNEL.md
```

安全边界：

- 不开放路由器端口。
- 不把 `uploads/` 设成公开目录。
- 不把 SQLite 数据库目录暴露到公网。
- 不把 FastAPI 改成 `--host 0.0.0.0`。

Tunnel 配好后，用公网域名检查：

```powershell
Invoke-RestMethod https://api.你的域名.com/api/health
```

App Token 检查：

```powershell
$headers = @{ Authorization = "Bearer 你的APP_TOKEN" }
Invoke-RestMethod https://api.你的域名.com/api/auth/check -Headers $headers
```

## 3. iPhone 快捷指令

快捷指令名称：

```text
上传到小票夹
```

建议流程：

1. 从分享菜单接收图片。
2. 必要时把图片转换为 JPEG 或 PNG。
3. 使用“获取 URL 内容”。
4. 方法选择 `POST`。
5. URL 填：

```text
https://api.你的域名.com/api/upload-screenshot
```

请求体使用 `文件`，不要使用 `表单`：

```text
文件：转换后的图像
```

请求头：

```text
Upload-Token: 你的UPLOAD_TOKEN
User-Agent: TicketBox/1.0 iOS-Shortcut
```

成功后显示：

```text
已上传到小票夹
```

说明：

- 后端接受 `jpg`、`jpeg`、`png`、`webp`、`heic`。
- 当前 HEIC 会保存原图但跳过缩略图生成，所以快捷指令优先转 JPEG 或 PNG。
- iPhone 上传只使用 `UPLOAD_TOKEN`，不要使用 `APP_TOKEN`。
- iOS 26.4 真机已验证：`表单` 模式会导致 `invalid_request` 的概率更高，稳定配置是“请求正文：文件”。

## 4. Android 真机安装

手机准备：

1. 打开开发者选项。
2. 打开 USB 调试。
3. 用数据线连接 Windows。
4. 在手机弹窗中允许这台电脑调试。

本机如果没有 adb，可安装 Android Platform Tools。当前推荐使用官方 platform-tools：

```powershell
$adb = "E:\tools\android\platform-tools\adb.exe"
& $adb devices
```

构建灰度用户版：

```powershell
cd E:\projects\xiaopiaojia\android
$env:JAVA_HOME="C:\Program Files\Eclipse Adoptium\jdk-17.0.19.10-hotspot"
$env:Path="$env:JAVA_HOME\bin;$env:Path"
.\gradlew.bat :app:assembleGrayDebug --console=plain
```

安装并启动灰度用户版：

```powershell
cd E:\projects\xiaopiaojia
$adb = "E:\tools\android\platform-tools\adb.exe"
& $adb -s 设备序列号 install -r android\app\build\outputs\apk\gray\debug\app-gray-debug.apk
& $adb -s 设备序列号 shell am start -n com.ticketbox/.MainActivity
```

内部联调版：

```powershell
cd E:\projects\xiaopiaojia\android
.\gradlew.bat :app:assembleInternalDebug --console=plain
cd E:\projects\xiaopiaojia
$adb = "E:\tools\android\platform-tools\adb.exe"
& $adb -s 设备序列号 install -r android\app\build\outputs\apk\internal\debug\app-internal-debug.apk
& $adb -s 设备序列号 shell am start -n com.ticketbox.internal/.MainActivity
```

APK 位置：

```text
E:\projects\xiaopiaojia\android\app\build\outputs\apk\gray\debug\app-gray-debug.apk
E:\projects\xiaopiaojia\android\app\build\outputs\apk\internal\debug\app-internal-debug.apk
```

## 5. 一键预检

手机还没到时，只检查后端和测试上传：

```powershell
cd E:\projects\xiaopiaojia
powershell -ExecutionPolicy Bypass -File scripts\real_device_preflight.ps1 -SkipDevice
```

后端还没启动，只检查设备：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\real_device_preflight.ps1 -SkipBackend
```

手机到手后，构建、安装并启动：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\real_device_preflight.ps1 -BuildApk -Install -Launch
```

如果用 Cloudflare 域名做完整公网链路：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\real_device_preflight.ps1 `
  -ServerUrl https://api.你的域名.com `
  -SkipDevice
```

脚本默认从 `backend\.env` 读取 `APP_TOKEN` 和 `UPLOAD_TOKEN`，不会打印 Token。

## 6. USB 反向转发联调

如果真机上的 VPN、代理或运营商网络导致 Cloudflare HTTPS 握手失败，可以先用 adb reverse 验证 App 和后端闭环：

```powershell
$adb = "E:\projects\xiaopiaojia\.toolchains\android-sdk\platform-tools\adb.exe"
& $adb -s 设备序列号 reverse tcp:8000 tcp:8000
& $adb -s 设备序列号 reverse --list
```

internalDebug 包支持仅用于联调的 intent 绑定入口，避免中文输入法改写同步地址或访问口令：

```powershell
cd E:\projects\xiaopiaojia\android
.\install_debug_apk.bat -Flavor internal -Build -ReverseBackend -ClearData -DebugBind
```

等价的底层 adb 命令如下：

```powershell
$envLines = [System.IO.File]::ReadAllLines("E:\projects\xiaopiaojia\backend\.env", [System.Text.UTF8Encoding]::new($false))
$appToken = (($envLines | Where-Object { $_ -match "^APP_TOKEN=" }) -replace "^APP_TOKEN=", "").Trim()
& $adb -s 设备序列号 shell am start -n com.ticketbox.internal/.MainActivity `
  --es ticketbox.debug.server_url "http://127.0.0.1:8000" `
  --es ticketbox.debug.app_token $appToken
```

说明：

- 这个入口只在 internal debuggable APK 中生效，灰度用户版不会响应。
- 不打印 Token，不进入 release 构建。
- `http://127.0.0.1:8000` 依赖 `adb reverse`，只用于 USB 联调。
- 正式使用仍然配置 `https://api.你的域名.com`。

## 7. App 绑定

首次打开 Android App：

```text
同步地址：服务拥有者提供的 HTTPS 地址
访问口令：服务拥有者提供的 App 访问口令
```

绑定成功后进入 App。灰度用户版设置页只显示账本状态和同步状态；内部联调版设置页才显示“运行诊断”。

灰度用户版设置页只显示：

- 当前账本
- 连接状态
- 最近上传
- 最近同步
- 存储状态
- 外观
- 数据与安全

内部联调版才显示诊断入口。诊断会检查：

- 访问凭证是否有效。
- 服务概况是否可读。
- 待确认、账本、统计、分类、重复检测是否可访问。
- 有待确认截图时，受保护缩略图是否可打开。

## 8. 端到端验收

按顺序验证：

1. iPhone 分享一张账单截图，执行“上传到小票夹”。
2. 后端返回 uploaded。
3. Android 待确认页下拉刷新，看到一条 pending。
4. 打开编辑页，确认截图缩略图或原图入口可用。
5. 填写金额、商家、分类、备注和实际消费时间。
6. 保存后金额仍按分保存，界面按元显示。
7. 点击确认入账。
8. 账本页出现该账单。
9. 统计页本月总额、分类金额、最近 7 天统计更新。
10. 断开网络后打开账本页，能看到 Room 本地缓存。

## 9. 常见问题

`invalid_token`：

```text
检查 iPhone 是否使用 Upload-Token。
检查 Android 是否使用 Authorization: Bearer APP_TOKEN。
不要用 /api/health 判断 Token 是否正确。
```

`unsupported_file_type`：

```text
快捷指令把图片转成 JPEG 或 PNG 后再上传。
```

`file_too_large`：

```text
单图最大 10MB。快捷指令可先压缩图片。
```

Android 无法连接本机：

```text
真机建议用 Cloudflare HTTPS 域名。
模拟器访问 Windows 本机后端用 http://10.0.2.2:8000。
USB 联调可用 adb reverse 后填 http://127.0.0.1:8000。
```

真机访问 Cloudflare 域名时报 `SSLHandshakeException: connection closed`：

```text
优先检查手机上的 VPN、代理、fake-ip DNS 或安全软件。
先用 adb reverse 验证 App/后端闭环，再切回 Cloudflare HTTPS 域名。
```

ADB 找不到设备：

```text
确认 USB 调试已打开。
确认手机弹窗已允许这台电脑。
换数据线或 USB 口。
运行 .\install_debug_apk.bat -ListDevices 查看状态。
```

HEIC 不能预览：

```text
后端可保存 HEIC 原图，但当前缩略图生成会跳过 HEIC，Android 预览需要降级处理。
iPhone 快捷指令优先转 JPEG 或 PNG。
```

## 10. 官方资料

- Android 真机运行与调试：https://developer.android.com/studio/run/device
- Android Debug Bridge：https://developer.android.com/tools/adb
- Cloudflare Tunnel 本地应用发布：https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/install-and-setup/tunnel-guide/local/
- Apple 快捷指令“获取 URL 内容”：https://support.apple.com/guide/shortcuts/use-the-get-contents-of-url-action-apd58d46713f/ios
