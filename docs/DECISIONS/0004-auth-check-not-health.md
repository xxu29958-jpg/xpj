# 0004 绑定服务器使用认证检查接口

## 决策

Android 后续首次绑定服务器时使用：

```http
GET /api/auth/check
Authorization: Bearer APP_TOKEN
```

不能使用 `/api/health` 判断 Token 是否正确。

## 原因

`/api/health` 只表示服务可达，不代表 App Token 有效。

## 不允许回退

绑定流程不得用 `/api/health` 替代 `/api/auth/check`。
