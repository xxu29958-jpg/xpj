# v0.3 回滚说明

v0.3 是破坏式身份迁移：运行时不兼容旧 `APP_TOKEN` / `UPLOAD_TOKEN`。

## 回滚点

代码回滚点：

```text
v0.2.0-rc1
```

## 自动备份

后端启动迁移前会自动复制 SQLite：

```text
backend\data\ticketbox.db
-> backend\backups\ticketbox-pre-v0.3-YYYYMMDD-HHMMSS.db
```

`uploads/` 不移动、不删除，仍保留原路径。

## 回滚步骤

1. 停止后端。
2. 切回 `v0.2.0-rc1` 代码。
3. 用迁移前备份覆盖 `backend\data\ticketbox.db`。
4. 保持 `backend\uploads\` 原目录不变。
5. 启动后端。
6. 用 v0.2 的 Android/iOS 配置重新验证上传、pending、confirm 和图片读取。

## 风险边界

- v0.3 创建的账号、设备、pairing code、upload link 不会被 v0.2 使用。
- 回滚后仍只能依赖 v0.2 的旧 token 模型。
- 如果 v0.3 期间新增了账单，回滚到迁移前数据库会丢失这些新增账单；需要先导出或手工合并。
