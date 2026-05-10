# iPhone 快捷指令上传说明

当前不做 iPhone App，使用 iOS 快捷指令从分享菜单上传截图。

v0.3 以后不再使用 `Upload-Token` 请求头。iPhone 上传改为 **UploadLink URL**，也就是一个带上传密钥的独立 URL。

## 前提

- Windows 后端已启动在 `http://127.0.0.1:8000`。
- Cloudflare Tunnel 已把公网域名映射到本机后端，例如：

```text
https://api.我的域名.com -> http://127.0.0.1:8000
```

- 已通过 `scripts\bootstrap_owner.ps1` 初始化 owner，拿到了 `upload_key` 和完整 UploadLink URL。

## UploadLink 地址

v0.3 初始化后，owner 会拿到类似下面的 UploadLink：

```text
https://api.我的域名.com/u/<upload_key>?tz=Asia/Shanghai
```

- `<upload_key>` 是服务端生成的随机字符串，只显示一次。
- `?tz=Asia/Shanghai` 是可选时区参数；iPhone 可换成其他 IANA 时区名，不填时后端用默认时区。
- 这个 URL 本身携带鉴权信息，快捷指令不再需要额外配置 `Upload-Token` 请求头。

## 快捷指令

名称：

```text
上传到小票夹
```

iOS 26.4 真机验证通过。**关键约束**：动作 2 的「URL」字段必须粘贴 Owner Console 给出的<u>完整公网 URL</u>（以 `https://` 开头），iPhone 才会把它当成有效 URL；只复制 `/u/...` 相对路径或 `/u/***` 掩码会被 iPhone 直接判定为无效 URL。

操作顺序：

1. 在「快捷指令」App 中创建新快捷指令；详情里开启「在共享表单中显示」，接收类型只勾选「图像」。
2. **动作 1：转换图像**，格式选 JPEG。
3. **动作 2：URL**，把 Owner Console 创建/轮换 UploadLink 后显示的<u>完整公网 URL</u>整段粘贴进去（含 `https://` 和 `?tz=Asia/Shanghai`）。<u>不要</u>只粘贴 `/u/...` 相对路径，<u>不要</u>使用 `/u/***` 掩码，<u>不要</u>再手动拼接一次 `?tz=`。
4. **动作 3：获取 URL 内容**：
   - URL：选择上一步「URL」
   - 方法：`POST`
   - 请求正文：`文件`（不是表单、不是 JSON）
   - 文件：选择「转换后的图像」
5. **动作 4：显示通知**「已上传到小票夹」。

可选：在动作 3 的请求头里加 `User-Agent: TicketBox/1.0 iOS-Shortcut` 区分快捷指令流量；Cloudflare 偶尔会把没有标准 `User-Agent` 的请求拦截为 `error code: 1010`。

**已废弃 / 不要再写到快捷指令里**：

- 「从输入获取图片」动作（接收类型已经限定为图像，多此一举）。
- 把「快捷指令输入」直接放进 URL 字段（URL 字段必须是完整公网 URL）。
- 只复制 `/u/...` 相对路径。
- 使用 `/u/***` 掩码链接。
- 手动追加 `?tz=Asia/Shanghai`（Owner Console 已经带上）。
- `Upload-Token` 请求头（v0.3 已移除）。

旧版快捷指令如果仍使用 `Upload-Token` 和 `/api/upload-screenshot`，后端会返回：

```json
{"error":"legacy_auth_removed","message":"登录已失效，请重新绑定设备。"}
```

成功上传后，「获取 URL 内容」会返回类似：

```json
{"id":9,"public_id":"018f4f90-2c20-7a2f-9d1c-6a6b81e69b2d","status":"pending","message":"uploaded"}
```

## 不要使用表单模式

iOS 26.4 实测中，`表单` 模式容易把"转换后的图像"当作普通表单值发送，后端收不到真正的图片文件，会返回：

```json
{"error":"invalid_request","message":"请求参数不正确。"}
```

所以当前推荐只使用 `文件` 请求正文。后端仍兼容标准 `multipart/form-data`，并会识别 `file`、`image`、`photo`、`screenshot` 或表单里的第一个文件字段；但它主要用于 curl、测试脚本或其他能明确发送文件字段的客户端，不作为 iOS 快捷指令首选配置。

## 注意事项

- 不要把 admin token、session token 或 pairing code 放到 iPhone 快捷指令里。
- iPhone 只使用 UploadLink URL，它是独立的、只用于上传的凭证。
- 不要把完整 UploadLink URL 发到聊天、日志、截图或工单里；需要排查时把 `/u/<upload_key>` 打码成 `/u/***`。
- 后端必须用 `--no-access-log` 方式启动，避免 Uvicorn 访问日志写下完整 UploadLink 路径。Cloudflare 或其他代理日志也不要保存完整 URL。
- `User-Agent` 必须一起添加。Cloudflare 可能会把没有标准 `User-Agent` 的快捷指令请求拦截为 `error code: 1010`，手机上会显示成"网络中断"。
- `?tz=...` 不参与鉴权，只用于上传后 OCR 草稿时间解析。
- 推荐快捷指令先转换为 JPEG 或 PNG，减少上传体积并提升预览稳定性；v0.3 也支持 HEIC 原图，后端会做真实解码校验并尝试生成 JPEG 缩略图。
- 如果提示"表单里没有找到图片文件"，检查请求正文是否误选为 `表单`，或表单字段是不是普通文本；iOS 26.4 推荐改为 `文件`。
- 离开家里 Wi-Fi 后仍然使用完整 UploadLink URL。如果蜂窝网络下提示"网络中断"，先用 Safari 打开 `https://api.我的域名.com/api/health`。
- 不要开放路由器端口。
- 不要把 Windows `uploads` 目录公开到公网。
