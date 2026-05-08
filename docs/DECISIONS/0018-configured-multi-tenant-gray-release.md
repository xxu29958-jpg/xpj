# 0018 配置式多租户灰度隔离

日期：2026-05-05

## 决策

灰度版采用配置式多租户，不做账号密码注册系统。

配置入口：

```env
TENANTS_JSON=[
  {"id":"owner","name":"我的小票夹","upload_token":"...","app_token":"..."},
  {"id":"tester_1","name":"灰度用户1","upload_token":"...","app_token":"..."}
]
```

未配置 `TENANTS_JSON` 时，兼容旧的 `UPLOAD_TOKEN` 和 `APP_TOKEN`，自动生成默认租户 `owner`。

## 原因

当前项目目标是私人灰度试用，不是商业 SaaS。配置式租户能满足隔离和灰度需求，同时避免引入注册、密码、找回、邮箱、短信、多用户后台等复杂系统。

## 影响

- Expense 增加 `tenant_id`。
- CategoryRule 增加 `tenant_id`。
- DuplicateIgnore 增加 `tenant_id`。
- 所有账单、图片、统计、分类规则、重复检测、CSV 都必须按 `tenant_id` 过滤。
- 旧数据迁移到 `owner`。
- Android 绑定后显示账本名，不显示服务器诊断。

## 禁止

- 禁止跨租户查询。
- 禁止用前端过滤代替后端隔离。
- 禁止图片接口不校验租户。
- 禁止 CSV 导出跨租户。
