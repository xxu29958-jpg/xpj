# 小票夹数据持久化与清理策略

## 数据职责

小票夹的数据分三层：

1. Windows 后端 SQLite
   - 文件：`backend/data/ticketbox.db`
   - 职责：账单主库、账本隔离、分类规则、重复检测记录、统计来源
   - 这是长期可信数据源。

2. Windows 后端 uploads
   - 文件夹：`backend/uploads/{ledger_id}/YYYY/MM/`
   - 职责：保存 iPhone / Android 上传的账单截图和缩略图
   - 数据库只保存相对路径，不保存本机绝对路径。
   - 历史 `backend/uploads/YYYY/MM/` 路径不会在启动时自动移动；如需整理，可显式运行维护脚本调用 `migrate_upload_paths_to_tenant_dirs()`。未迁移的无账本前缀路径只兼容默认旧账本读取；文件不存在时不报错，访问返回 `image_not_found`。
   - uploads 不作为静态目录公开，只能通过受保护图片接口访问。

3. Android Room
   - 职责：confirmed 账本本地缓存和离线查看
   - 不是主库。
   - 远端同步成功后更新本地；远端失败时账本页才回退显示本地缓存。

## 生命周期规则

账单状态仍保持主线：

```text
上传截图 -> pending -> 用户确认 -> confirmed -> Room 缓存 -> 账本 / 统计
```

清理策略不得改变业务状态：

- 上传只创建 pending。
- OCR 只填草稿。
- 重复检测只提示。
- 清理图片不删除 confirmed 账单数据。
- 清理 rejected 图片不删除 rejected 行。
- 孤儿文件清理只处理数据库没有引用的 uploads 文件。

## 配置项

```env
DELETE_IMAGE_AFTER_CONFIRM=false
DELETE_IMAGE_AFTER_DAYS=0
DELETE_REJECTED_AFTER_DAYS=0
ORPHAN_UPLOAD_GRACE_HOURS=24
```

含义：

- `DELETE_IMAGE_AFTER_CONFIRM`
  - 确认入账时是否立刻删除原图。
  - 当前建议保持 `false`。

- `DELETE_IMAGE_AFTER_DAYS`
  - confirmed 账单图片保留天数。
  - `0` 表示禁用定期清理。

- `DELETE_REJECTED_AFTER_DAYS`
  - rejected 账单图片保留天数。
  - `0` 表示禁用定期清理。

- `ORPHAN_UPLOAD_GRACE_HOURS`
  - 孤儿文件扫描的保护窗口。
  - 默认 24 小时，避免误删刚上传但事务未完成的文件。

## 维护接口

维护接口只允许 admin scope token 调用，并只作用于当前 admin 上下文对应的账本：

```http
Authorization: Bearer <admin_token>
```

接口：

- `POST /api/maintenance/cleanup-images`
  - 按 `DELETE_IMAGE_AFTER_DAYS` 清理当前 admin 上下文账本的 confirmed 图片和缩略图。

- `POST /api/maintenance/cleanup-rejected`
  - 按 `DELETE_REJECTED_AFTER_DAYS` 清理当前 admin 上下文账本的 rejected 图片和缩略图。

- `POST /api/maintenance/cleanup-orphans?dry_run=true`
  - 扫描当前账本目录下数据库未引用的 uploads 文件。
  - 默认 dry-run，不删除。

- `POST /api/maintenance/cleanup-orphans?dry_run=false`
  - 删除超过保护窗口的孤儿 uploads 文件。

## Windows 维护脚本

推荐先备份，再清理：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\maintenance_ticketbox.ps1 -Backup
```

检查孤儿文件但不删除：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\maintenance_ticketbox.ps1 -CleanupOrphans
```

确认无误后删除孤儿文件：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\maintenance_ticketbox.ps1 -CleanupOrphans -DeleteOrphans
```

清理 confirmed / rejected 历史图片：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\maintenance_ticketbox.ps1 -CleanupConfirmedImages -CleanupRejectedImages
```

## 备份建议

灰度前至少保留：

- 最近 7 天每日一份 SQLite 备份。
- 每次大改前手动备份。
- 不要把真实 Token 和备份数据库提交到 Git。

备份目录(`backend/app/services/backup_service.py:_BACKUP_DIR = DATA_ROOT / "backups"`):

```text
<DATA_ROOT>/backups/
```

`DATA_ROOT` 跟随部署形态:源码运行 `backend/`,冻结 EXE 部署 `ticketbox-data/`。该目录用于本机运维，不应提交。

## 数据清理底线

- 不做远程文件管理。
- 不提供任意路径删除。
- 不清理 uploads 目录外文件。
- 不让普通 Android App 展示维护接口。
- 不因为图片丢失影响 confirmed 账本展示。
- 不把 Android Room 当主库。
