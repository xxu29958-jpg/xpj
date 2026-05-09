# Android 上传截图规格

日期：2026-05-05

## 1. 目标

Android App 自身也能上传账单截图，不再只依赖 iPhone 快捷指令。

## 2. 用户流程

```text
待确认页
  -> 上传截图
  -> 系统 Photo Picker
  -> 选择账单截图
  -> App 上传
  -> 后端创建待确认账单
  -> 自动刷新待确认页
```

## 3. 权限策略

使用 Android 官方 Photo Picker。

原则：

- 不申请全相册权限。
- 用户只授权本次选择的图片。
- App 只读取用户选择的 URI。
- 上传完成后不长期保存原图副本。

## 4. 接口

Android App 使用：

```http
POST /api/app/upload-screenshot
Authorization: Bearer APP_TOKEN
X-Timezone: 手机系统 IANA 时区
Content-Type: multipart/form-data
file=<image>
```

不使用：

```http
Upload-Token
```

`Upload-Token` 只保留给 iPhone 快捷指令。

## 5. Repository 边界

Screen：

- 触发 Photo Picker。
- 把选中的 URI 传给 ViewModel。

ViewModel：

- 管理上传中、成功、失败状态。
- 上传成功后刷新 pending。

Repository：

- 接收已准备好的图片字节，不在主线程读取或压缩大图。
- 生成 multipart/form-data。
- 调用 API。
- 解析统一错误。

ApiService：

- 定义 Retrofit upload endpoint。

## 6. 用户反馈

上传中：

```text
正在上传截图...
```

成功：

```text
截图已上传，等你确认。
```

失败：

```text
没有上传成功，请稍后再试。
```

不展示：

- HTTP 状态码。
- multipart。
- endpoint。
- token。
- 文件本机路径。

## HEIC 策略

- Android 选到 HEIC/HEIF 时，优先用系统 `ImageDecoder` 解码并转成 JPEG 上传。
- 如果系统无法解码，App 会按原图上传，交给后端 `pillow-heif` 做真实解码校验；后端拒绝伪造或损坏 HEIC。
- 用户可见结果仍然只有上传成功或失败文案，不展示 HEIC、解码器或接口细节。

调试构建允许在 Logcat 的 `TicketboxNetwork` tag 记录上传耗时分段：

```text
prepare_ms      Photo Picker 返回 URI 后，本机读取/采样/压缩耗时
network_ms      Retrofit 上传请求耗时，包含公网链路
server_ms       后端返回的服务端总耗时
server_breakdown 后端 body/form、文件保存、DB 创建分段
```

这些字段只用于定位“上传慢”发生在手机预处理、网络链路还是 Windows 后端，不进入普通用户界面。

## 7. 验收

- 点击“上传截图”能打开系统 Photo Picker。
- 选择图片后能上传。
- 上传成功后 pending 列表刷新。
- 上传失败不白屏。
- Android 不保存 Upload Token。
- Android 不申请全相册权限。

## 8. 当前落地

已实现：

- 后端 `POST /api/app/upload-screenshot`，使用 `Authorization: Bearer APP_TOKEN`。
- Android `ApiService.uploadScreenshot` 使用 Retrofit multipart，并随请求发送手机系统时区 `X-Timezone`。
- `ExpenseRepository.uploadScreenshot` 统一处理 multipart、错误和最近上传时间。
- 选图后的图片读取、采样和压缩已移到 IO 线程，避免阻塞 Compose 主线程。
- `PendingViewModel` 管理上传中、成功、失败状态。
- 待确认页主按钮“上传截图”打开系统 Photo Picker。
- 真机验证 Photo Picker 可打开，界面显示系统“安全访问”说明。

仍需真人确认的端到端步骤：

- 从 Photo Picker 选择一张真实账单。
- 上传后 pending 自动刷新。
- 编辑、确认、账本、统计联动验收。
