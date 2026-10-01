# iPhone 快捷指令上传说明

当前不做 iPhone App，使用 iOS 快捷指令从分享菜单上传截图。

iPhone 使用 **UploadLink URL** 上传，也就是一个带上传密钥的独立 URL，无需另填 `Upload-Token` 请求头。

## 前提

- Windows 后端已启动在 `http://127.0.0.1:8000`。
- Cloudflare Tunnel 已把公网域名映射到本机后端，例如：

```text
https://api.我的域名.com -> http://127.0.0.1:8000
```

- 已完成正式 Windows 安装和首用配对，具体步骤见 [Windows 首装配对](BOOTSTRAP.md)。从电脑端打开本机管理页，在「设置」保存手机可访问的 HTTPS 地址，再进入「iPhone 上传链接」点击「新建上传链接」。复制本次显示的完整 URL；正式首装返回的是配对码，上传链接由这个页面单独创建。

## UploadLink 地址

在本机管理页创建链接后，会显示类似下面的 UploadLink：

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

历史实机记录覆盖 iOS 26.4 的动作 1–3 上传链路和原先的静态通知。下面的回执判断、疑似重复与错误分支**尚待本次 iPhone 实机核准**。**关键约束**：动作 2 的「URL」字段必须粘贴 Owner Console 给出的<u>完整公网 URL</u>（以 `https://` 开头），iPhone 才会把它当成有效 URL；只复制 `/u/...` 相对路径或 `/u/***` 掩码会被 iPhone 直接判定为无效 URL。

操作顺序：

1. 在「快捷指令」App 中创建新快捷指令；详情里开启「在共享表单中显示」，接收类型只勾选「图像」。
2. **动作 1：转换图像**，格式选 JPEG。
3. **动作 2：URL**，把 Owner Console 创建/轮换 UploadLink 后显示的<u>完整公网 URL</u>整段粘贴进去（含 `https://` 和 `?tz=Asia/Shanghai`）。可以点 Owner Console 的「复制完整 URL」按钮一键复制，或用 iPhone 相机扫页面上的二维码后长按横幅选「拷贝」（<u>不要</u>直接打开链接——上传地址只接受快捷指令发出的 POST 上传，浏览器直接打开会提示无效）。<u>不要</u>只粘贴 `/u/...` 相对路径，<u>不要</u>使用 `/u/***` 掩码，<u>不要</u>再手动拼接一次 `?tz=`。
4. **动作 3：获取 URL 内容**：
   - URL：选择上一步「URL」
   - 方法：`POST`
   - 请求正文：`文件`（不是表单、不是 JSON）
   - 文件：选择「转换后的图像」
5. **动作 4：设置变量**，把「URL 内容」保存为「上传响应」。后面的「获取词典值」都明确选择这个变量作为词典。
6. 分别添加两个**获取词典值**动作，从「上传响应」取 `message` 和 `public_id`；将输出分别命名为「回执消息」和「账单编号」。
7. 添加**如果**，选择满足**全部**条件：「回执消息」等于 `uploaded`，并且「账单编号」有任何值。条件满足时，才从「上传响应」取 `duplicate_status`：等于 `suspected` 时显示「小票夹已收到图片，但疑似重复，请到收件核对」；否则显示「小票夹已收到图片，请到收件核对」。外层「否则」显示「未确认收到，请保留图片并到收件核对」。

“已收到图片”表示服务器已接收，账单仍需人工核对。如果「获取 URL 内容」或词典读取提前报错中断，后续通知可能不会执行；保留原图并先查看收件，确认结果后再决定是否重试。不能用缺少 `duplicate_status` 或没有报错来判断上传成功。

条件分支和词典取值的搭建方法见 Apple 官方的[如果操作](https://support.apple.com/guide/shortcuts/use-if-actions-apd83dcd1b51/9.0/ios/26)及[获取词典值](https://support.apple.com/guide/shortcuts/get-dictionary-value-action-apdf01294032/9.0/ios/26)说明；它们不代替本次快捷指令的实机运行证据。

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
{"error":"legacy_auth_removed","message":"请使用新版 iOS 上传链接。"}
```

成功上传后，「获取 URL 内容」会返回类似：

```json
{
  "id": 9,
  "public_id": "018f4f90-2c20-7a2f-9d1c-6a6b81e69b2d",
  "enrichment_task_public_id": "018f4f90-2c20-7a2f-9d1c-6a6b81e69b2e",
  "status": "pending",
  "message": "uploaded",
  "image_hash": "0a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f9",
  "thumbnail_path": null,
  "duplicate_status": "none",
  "duplicate_of_id": null,
  "upload_size_bytes": 102400,
  "duration_ms": 180,
  "timing_ms": {"body_read_ms": 20, "file_save_ms": 60, "db_create_ms": 40, "total_ms": 180}
}
```

先核对 `message = uploaded` 和非空 `public_id`，再判断重复提示。`duplicate_status` 在响应返回前同步算好：`none` = 没发现重复，`suspected` = 与已有小票疑似重复（此时 `duplicate_of_id` 指向疑似原票）。

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
- 发生代理拦截时，可添加上述 `User-Agent` 辅助排查；它不能代替上传链接或成功回执。
- `?tz=...` 不参与鉴权，只用于上传后 OCR 草稿时间解析。
- 推荐快捷指令先转换为 JPEG 或 PNG，减少上传体积并提升预览稳定性；v0.3 也支持 HEIC 原图，后端会做真实解码校验并尝试生成 JPEG 缩略图。
- 如果提示"表单里没有找到图片文件"，检查请求正文是否误选为 `表单`，或表单字段是不是普通文本；iOS 26.4 推荐改为 `文件`。
- 上传失败时（4xx）后端返回的是 `{"error":"...","message":"..."}` JSON 信封，例如 401 `invalid_token`（链接失效）、429 `upload_throttled` / `upload_daily_quota_exhausted`（限流/日配额）。它不满足成功回执条件，即使继续执行分支，也只应提示未确认收到。iOS 对非 2xx 响应会在哪里中断、显示什么系统错误，以及链接撤销、限流、断网和回复丢失后的实际通知仍**待真机实测**；排查时结合收件记录和已脱敏诊断。
- 离开家里 Wi-Fi 后仍然使用完整 UploadLink URL。如果蜂窝网络下提示"网络中断"，先用 Safari 打开 `https://api.我的域名.com/api/health`。
- 不要开放路由器端口。
- 不要把 Windows `uploads` 目录公开到公网。
