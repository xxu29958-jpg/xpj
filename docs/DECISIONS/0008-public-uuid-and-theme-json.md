# 0008 公共 UUID 与主题 JSON 边界

日期：2026-05-04

## 决定

账单增加内部公共标识：

```text
public_id: UUID
```

它用于导出、跨端同步、排查问题和未来多端合并，不替代当前后端自增 `id` 与 Android `serverId` 的第一版闭环。

已落地规则：

- 后端 `Expense.public_id` 为唯一 UUID 字符串。
- 上传、待确认、已确认、手动记账、统计关联对象和导出都携带 `public_id`。
- Android DTO、Domain、Room Entity 都保存 `publicId`。
- Room `serverId` 和 `publicId` 都是唯一索引。
- Room 1 -> 2 迁移使用新表复制并重建索引，避免新增非空列造成 schema 校验失败。

主题可以演进为 JSON/token 配置，但普通用户界面不直接暴露 JSON。

## UI 规则

- 普通用户不看 UUID。
- 普通用户不编辑 JSON。
- UI 只显示“账单编号”“主题名”“颜色预览”“效果预览”等可理解内容。
- 高级调试信息必须折叠在详情里。

## 设计参考

小票夹 Android UI 采用 Material 3 组件和 token 思路，吸收 Apple HIG 的清晰、轻量、内容优先原则。可以参考大厂设计方法，但不直接复制具体产品界面。

港湾主题作为默认主题。主题 JSON 后续可以成为内部 token 配置来源，但用户只通过“外观”页面选择、预览和调整主题。

## 不做

- 第一版不迁移数据库主键到 UUID。
- 第一版不开放原始 JSON 主题编辑器。
- 第一版不在账单卡片上显示技术 id。
