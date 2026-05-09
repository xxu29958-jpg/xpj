# iPhone 快捷指令上传说明

当前不做 iPhone App，使用 iOS 快捷指令从分享菜单上传截图。

## 前提

- Windows 后端已启动在 `http://127.0.0.1:8000`。
- Cloudflare Tunnel 已把公网域名映射到本机后端，例如：

```text
https://api.我的域名.com -> http://127.0.0.1:8000
```

- `.env` 中已设置随机长字符串 `UPLOAD_TOKEN`。

## 上传自检

如果第一次配置，建议先做一个临时快捷指令测试 Token 和隧道：

1. 添加“获取 URL 内容”。
2. URL 填：

```text
https://api.我的域名.com/api/upload/check
```

3. 方法选择 `GET`。
4. 添加请求头：

```http
Upload-Token: 你的_UPLOAD_TOKEN
User-Agent: TicketBox/1.0 iOS-Shortcut
```

5. 后面添加“显示结果”。

成功时显示：

```json
{"status":"ok","max_upload_size_mb":10,"supported_file_types":["heic","jpeg","jpg","png","webp"],"recommended_body":"file"}
```

如果这里显示 `invalid_token`，说明 `UPLOAD_TOKEN` 粘错了。  
如果这里提示网络中断，先检查手机是否能打开 `https://api.我的域名.com/api/health`。

## 快捷指令

名称：

```text
上传到小票夹
```

推荐流程，已在 iOS 26.4 真机验证通过：

1. 快捷指令设置为“在分享表单中显示”。
2. 接收类型选择“图像”。
3. 添加“转换图像”动作，建议转换为 JPEG 或 PNG。
4. 添加“获取 URL 内容”动作。
5. URL 填：

```text
https://api.我的域名.com/api/upload-screenshot
```

6. 方法选择 `POST`。
7. 请求正文选择 `文件`，不要选择 `表单`。
8. 文件选择“转换后的图像”。
9. 添加请求头：

```http
Upload-Token: 你的_UPLOAD_TOKEN
User-Agent: TicketBox/1.0 iOS-Shortcut
X-Timezone: Asia/Shanghai
```

`X-Timezone` 填 iPhone 当前系统时区对应的 IANA 名称。中国大陆通常是 `Asia/Shanghai`；如果人在其他时区，填当地系统时区，后端会用它解析 OCR 草稿里的本地时间。旧快捷指令不填时会回落到后端默认时区。

10. 上传成功后显示“获取 URL 内容”的结果，看到类似下面内容才算成功：

```json
{"id":9,"public_id":"018f4f90-2c20-7a2f-9d1c-6a6b81e69b2d","status":"pending","message":"uploaded"}
```

11. 确认成功后，可以把显示结果改成：

```text
已上传到小票夹
```

## 不要使用表单模式

iOS 26.4 实测中，`表单` 模式容易把“转换后的图像”当作普通表单值发送，后端收不到真正的图片文件，会返回：

```json
{"error":"invalid_request","message":"请求参数不正确。"}
```

所以当前推荐只使用 `文件` 请求正文。后端仍兼容标准 `multipart/form-data`，并会识别 `file`、`image`、`photo`、`screenshot` 或表单里的第一个文件字段；但它主要用于 curl、测试脚本或其他能明确发送文件字段的客户端，不作为 iOS 快捷指令首选配置。

## 注意事项

- 不要把 `APP_TOKEN` 或 `ADMIN_TOKEN` 放到 iPhone 快捷指令里。
- iPhone 只使用 `UPLOAD_TOKEN`。
- `Upload-Token` 的值只填 token 本身，不要填 `Bearer`、冒号或引号。
- `User-Agent` 必须一起添加。Cloudflare 可能会把没有标准 `User-Agent` 的快捷指令请求拦截为 `error code: 1010`，手机上会显示成“网络中断”。
- `X-Timezone` 不参与鉴权，也不要填写 token；它只用于上传后 OCR 草稿时间解析。
- 推荐快捷指令先转换为 JPEG 或 PNG，减少上传体积并提升预览稳定性；v0.2 也支持 HEIC 原图，后端会做真实解码校验并尝试生成 JPEG 缩略图。
- 如果提示“表单里没有找到图片文件”，检查请求正文是否误选为 `表单`，或表单字段是不是普通文本；iOS 26.4 推荐改为 `文件`。
- 离开家里 Wi-Fi 后仍然使用 `https://api.zen70.cn/api/upload-screenshot`。如果蜂窝网络下提示“网络中断”，先用 Safari 打开 `https://api.zen70.cn/api/health`。
- 不要开放路由器端口。
- 不要把 Windows `uploads` 目录公开到公网。
