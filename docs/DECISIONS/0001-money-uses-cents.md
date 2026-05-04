# 0001 金额使用分保存

## 决策

全链路金额字段使用 `amount_cents`，单位为分。

后端数据库使用：

```text
amount_cents: int?
```

Android 本地数据库后续使用：

```text
amountCents: Long?
```

## 原因

金额不能使用 float/double 保存，避免浮点精度问题。

## 不允许回退

不得恢复为：

```text
amount: float
amount: Double?
数据库保存元
```
