# v0.3 回滚说明

v0.3 是破坏式身份迁移：运行时不兼容旧 `APP_TOKEN` / `UPLOAD_TOKEN`。

## 回滚点

代码回滚点：

```text
v0.2.0-rc1
```

## 自动备份

后端启动时如果发现数据库仍是 pre-v0.3 结构，会在迁移前自动复制 SQLite：

```text
backend\data\ticketbox.db
-> backend\backups\ticketbox-pre-v0.3-YYYYMMDD-HHMMSS.db
```

`uploads/` 不移动、不删除，仍保留原路径。

完成 v0.3 身份表迁移后，后续重启不会重复生成 `pre-v0.3` 备份。回滚时使用首次迁移前生成的这份备份。

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

## v1.0 迁移预检

进入 v1.0 数据迁移前，先从后端目录运行：

```powershell
cd E:\projects\xiaopiaojia\backend
.\.venv\Scripts\python.exe scripts\preflight_v1_migration.py --create-backup
```

脚本只做本机 SQLite 预检和备份，不修改业务数据、不执行 schema 迁移。`--create-backup` 会创建：

```text
backend\backups\ticketbox-pre-v1.0-YYYYMMDD-HHMMSS.db
```

返回 JSON 中 `ready=true` 才表示当前库具备 v0.9 基线表、关键索引，且最新备份是 `pre-v1.0` 类型回滚备份。`ready=false` 时不得继续做 v1.0 破坏式迁移；先按 `checks` 中的错误修复当前库或恢复到可升级基线。
