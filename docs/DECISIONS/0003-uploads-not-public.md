# 0003 uploads 不公开暴露

## 决策

`uploads/` 目录不能作为静态目录公开。

图片只能通过受保护接口访问：

```http
GET /api/expenses/{id}/image
Authorization: Bearer <session_token>
```

## 安全要求

- 上传文件随机命名。
- 数据库只保存相对路径。
- API 不返回 Windows 本机真实路径。
- 不使用 `StaticFiles` 暴露 uploads。

## 不允许回退

不得让客户端直接访问 uploads 路径。
