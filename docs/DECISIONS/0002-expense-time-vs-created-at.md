# 0002 区分消费时间和创建时间

## 决策

`expense_time` 表示实际消费时间。

`created_at` 只表示上传或创建时间。

## 统计口径

统计优先使用：

```text
expense_time
```

如果为空，使用：

```text
confirmed_at
```

## 时间格式

数据库保存 UTC 时间。

API 返回 ISO 8601 字符串。

Android 后续显示时转本地时间。

## 不允许回退

不得用 `created_at` 当消费时间统计。
