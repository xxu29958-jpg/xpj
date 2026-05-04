# iPhone 快捷指令上传说明

第一版不做 iPhone App，使用 iOS 快捷指令从分享菜单上传截图。

## 前提

- Windows 后端已启动在 `http://127.0.0.1:8000`。
- Cloudflare Tunnel 已把公网域名映射到本机后端，例如：

```text
https://api.我的域名.com -> http://127.0.0.1:8000
```

- `.env` 中已设置随机长字符串 `UPLOAD_TOKEN`。

## 快捷指令

名称：

```text
上传到小票夹
```

流程：

1. 快捷指令设置为“在分享表单中显示”。
2. 接收类型选择“图像”。
3. 添加“转换图像”动作，建议转换为 JPEG 或 PNG。
4. 添加“获取 URL 内容”动作。
5. URL 填：

```text
https://api.我的域名.com/api/upload-screenshot
```

6. 方法选择 `POST`。
7. 请求正文选择 `表单`。
8. 表单字段名填：

```text
file
```

9. 表单值选择转换后的图片文件。
10. 添加请求头：

```http
Upload-Token: 你的_UPLOAD_TOKEN
```

11. 上传成功后显示：

```text
已上传到小票夹
```

## 注意事项

- 不要把 `APP_TOKEN` 或 `ADMIN_TOKEN` 放到 iPhone 快捷指令里。
- iPhone 只使用 `UPLOAD_TOKEN`。
- 后端可以接受 HEIC，但第一版 Android 不保证 HEIC 原图预览；建议快捷指令转换为 JPEG 或 PNG。
- 不要开放路由器端口。
- 不要把 Windows `uploads` 目录公开到公网。
