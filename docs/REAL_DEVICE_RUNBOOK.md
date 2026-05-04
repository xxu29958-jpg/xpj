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

请求体使用 `multipart/form-data`：

```text
字段名：file
字段值：图片文件
```

请求头：

```text
Upload-Token: 你的UPLOAD_TOKEN
```

成功后显示：

```text
已上传到小票夹
```

说明：

- 后端接受 `jpg`、`jpeg`、`png`、`webp`、`heic`。
- 第一版 Android 预览 HEIC 不做强保证，所以快捷指令优先转 JPEG 或 PNG。
- iPhone 上传只使用 `UPLOAD_TOKEN`，不要使用 `APP_TOKEN`。

## 4. Android 真机安装

手机准备：

1. 打开开发者选项。
2. 打开 USB 调试。
3. 用数据线连接 Windows。
4. 在手机弹窗中允许这台电脑调试。

列出设备：

```powershell
cd E:\projects\xiaopiaojia\android
.\install_debug_apk.bat -ListDevices
```

构建、安装并启动：

```powershell
.\install_debug_apk.bat -Build -Launch
```

如果同时连了多台设备：

```powershell
.\install_debug_apk.bat -ListDevices
.\install_debug_apk.bat -Serial 设备序列号 -Build -Launch
```

APK 位置：

```text
E:\projects\xiaopiaojia\android\app\build\outputs\apk\debug\app-debug.apk
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

## 6. App 绑定

首次打开 Android App：

```text
服务器地址：https://api.你的域名.com
App Token：backend\.env 里的 APP_TOKEN
```

绑定成功后进入 App。进入“设置”页，点击“联调自检”。

自检会检查：

- `/api/auth/check`
- 服务器非敏感状态
- pending 列表
- confirmed 分页
- 月度统计
- 分类列表
- 月份列表
- 重复检测
- 受保护缩略图接口

## 7. 端到端验收

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

## 8. 常见问题

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
后端可保存 HEIC，但第一版 Android 不保证预览 HEIC。
iPhone 快捷指令优先转 JPEG 或 PNG。
```

## 9. 官方资料

- Android 真机运行与调试：https://developer.android.com/studio/run/device
- Android Debug Bridge：https://developer.android.com/tools/adb
- Cloudflare Tunnel 本地应用发布：https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/install-and-setup/tunnel-guide/local/
- Apple 快捷指令“获取 URL 内容”：https://support.apple.com/guide/shortcuts/use-the-get-contents-of-url-action-apd58d46713f/ios
