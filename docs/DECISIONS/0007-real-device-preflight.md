# 0007 实机联调预检

## 状态

已采纳。

## 决策

实机联调使用两层检查：

1. Windows 本地脚本 `scripts\real_device_preflight.ps1` 检查后端、session token、UploadLink 测试上传和 Android 设备安装。
2. Android App 设置页的“联调自检”检查已绑定服务器的 API 契约和受保护图片链路。

## 原因

小票夹的首个真实验收不是单个接口，而是：

```text
iPhone 上传 -> Windows 后端 -> Android 待确认 -> 编辑确认 -> 本地缓存和统计
```

把预检做成脚本可以减少手工排错；把 App 内自检保留在设置页，可以在真机、Cloudflare 域名和实际 session token 下重复验证。

## 约束

- 预检脚本不读取旧 `APP_TOKEN` / `UPLOAD_TOKEN`，只接受 `-SessionToken` / `-UploadLink` 参数或 `TICKETBOX_SESSION_TOKEN` / `TICKETBOX_UPLOAD_LINK` 环境变量，并且不得打印凭证。
- 预检脚本只上传内置 1x1 PNG 测试图，不读取任意用户文件。
- 设备安装复用 `android\scripts\install_debug_apk.ps1`，避免重复维护 ADB 逻辑。
- 任何联调检查都不能公开 `uploads/`，不能返回 Windows 本机真实路径。
- 不能为了真机联调把后端改成监听 `0.0.0.0`。

## 后续

如果未来增加正式 Release 包，可以新增 release 安装脚本，但 debug 安装链路仍然保留给本机联调。
