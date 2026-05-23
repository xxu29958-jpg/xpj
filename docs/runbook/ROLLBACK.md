# 版本回滚 Runbook

适用于 Windows 后端 + Cloudflare Tunnel + Android 灰度的部署形态，覆盖代码、数据库、APK、网络入口四条线的回滚顺序与限制。

## 适用范围与不可逆边界

回滚前必须先确认目标版本是否在"允许向下"范围内：

| 版本变更 | 是否允许回滚 | 说明 |
|---|---|---|
| 后端补丁（同一 minor 内） | ✅ 始终可逆 | `git revert` + 同备份 SQLite |
| Android 补丁（同一 minor 内） | ✅ 始终可逆 | 卸载灰度 APK，装上一版即可，Pairing 配对仍有效 |
| 后端 minor 降级（v0.9 → v0.8） | ⚠️ 数据库需先停写 | v0.9 新增 Reports/Goals/DashboardCard 表，回滚后这些表保留但 v0.8 不读，不影响业务；服务端预算（v0.8）→ v0.7 同理 |
| Android minor 降级 | ⚠️ 必须重新 Pairing | session token 在 Android 端 Keystore 中；旧 APK 不识别新 token，需重新配对 |
| **identity_schema 降级（任何方向越过 v0.3）** | ❌ 禁止 | `identity_schema=v0.3` 是 v0.3 以来的稳定契约；v0.3 之前的 `APP_TOKEN`/`UPLOAD_TOKEN` 模型已永久退役 |
| Cloudflare Tunnel 配置变更 | ✅ 可逆 | 保留上一版 `config.yml` 即可切回 |

## 回滚顺序

按以下顺序执行，避免数据不一致：

1. **停服**：[scripts/stop_backend.ps1](../../scripts/stop_backend.ps1) 或 Windows 服务面板停止 ticketbox
2. **备份当前库**：避免回滚后悔时找不到现场（见下方"数据库备份与恢复"）
3. **代码切换**：`git checkout <旧 tag>`
4. **数据库回滚**（如需要）
5. **重启**：[scripts/start_backend.ps1](../../scripts/start_backend.ps1)
6. **Android APK 回退**（如需要）：见 [RELEASE_PACKAGING.md](RELEASE_PACKAGING.md)
7. **网络入口回退**（如需要）：见 [CLOUDFLARE_TUNNEL.md](CLOUDFLARE_TUNNEL.md)
8. **验收**：见本文末"验收清单"

## 后端代码回滚

定位上一稳定 tag：

```powershell
git tag --sort=-version:refname | Select-Object -First 10
```

切换：

```powershell
git fetch --tags
git checkout <tag>          # 例如 v0.8.0
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

`backend/app/version.py` 中 `BACKEND_VERSION` 必须与目标 tag 一致——这是 [docs/architecture/VERSION.md](../architecture/VERSION.md) 定义的版本真值源。

## 数据库备份与恢复

### 手动备份当前库（回滚前必做）

两个脚本在不同目录，**统一从项目根运行**避免 cd 切换造成的相对路径歧义：

```powershell
# 备份脚本位于 backend\scripts\backup_database.ps1
# (根目录 scripts\ 下没有 backup_database.ps1，不要写 scripts\backup_database.ps1)
cd E:\projects\xiaopiaojia
powershell -ExecutionPolicy Bypass -File backend\scripts\backup_database.ps1
```

输出到 `backend\backups\ticketbox-YYYYMMDD-HHMMSS.db`（SQLite 在线备份，不需要停后端）。Windows 计划备份配置见 [WINDOWS_BACKUP_TASK.md](WINDOWS_BACKUP_TASK.md)。

### 恢复到某个备份

```powershell
# restore 脚本位于根目录 scripts\restore_ticketbox_db.ps1（跟备份脚本路径不同）
cd E:\projects\xiaopiaojia
powershell -ExecutionPolicy Bypass -File scripts\restore_ticketbox_db.ps1 -BackupPath backend\backups\ticketbox-YYYYMMDD-HHMMSS.db
```

脚本会拒绝在后端运行时覆盖数据库，并通过临时文件校验后再原子替换。`uploads/` 目录不动——图片文件路径以数据库 `expenses.image_path` 为权威，回滚库时图片自然对齐。

### 版本特定的数据库回滚注意

- **v0.9 → v0.8**：Reports/Goals/DashboardCard 表在 v0.8 代码中不会被读取，无需 drop；若希望干净环境可手工 drop，但**不要** drop budget 相关表（v0.8 仍读）
- **v0.8 → v0.7**：服务端 budget 表 v0.7 不读；同上，保留即可
- **v0.5 及以下**：已不支持，禁止回滚

## v1.0 迁移预检

进入 v1.0 破坏式迁移前必跑：

```powershell
cd E:\projects\xiaopiaojia\backend
.\.venv\Scripts\python.exe scripts\preflight_v1_migration.py --create-backup
```

`--create-backup` 创建专用回滚备份：

```text
backend\backups\ticketbox-pre-v1.0-YYYYMMDD-HHMMSS.db
```

返回 JSON 中 `ready=true` 才表示当前库具备 v0.9 基线表、关键索引，且最新备份是 `pre-v1.0` 类型。`ready=false` 时不得继续做 v1.0 迁移；先按 `checks` 错误修复当前库或恢复到可升级基线。

## Android APK 回退

灰度用户安装路径：

1. 在 Android Studio 或本地保留上一版 `app-gray-debug.apk` / `app-gray-release.apk`
2. 卸载当前版本：`adb uninstall com.ticketbox.gray`
3. 安装旧版：`adb install app-gray-release.apk`
4. 用 [BOOTSTRAP.md](BOOTSTRAP.md) 生成新 Pairing Code，App 端重新绑定
5. Pairing 完成后 `syncConfirmed()` 自动从后端恢复已确认账单到 Room 缓存

打包流程见 [RELEASE_PACKAGING.md](RELEASE_PACKAGING.md)。

## Cloudflare Tunnel 配置回退

Tunnel 配置改动通常是路由/域名调整，回滚就是把 `config.yml` 切回上一版后 reload。详见 [CLOUDFLARE_TUNNEL.md](CLOUDFLARE_TUNNEL.md)。Windows 上 cloudflared 作为服务运行的话用 `Restart-Service cloudflared`。

## 验收清单

回滚后必须人工核对：

```powershell
# 1. 版本字符串四处一致
Select-String -Path backend\app\version.py -Pattern 'BACKEND_VERSION'
Select-String -Path android\app\build.gradle.kts -Pattern 'ticketboxVersionName'
Select-String -Path docs\architecture\VERSION.md -Pattern '当前版本'
Select-String -Path README.md -Pattern '当前版本'

# 2. 后端启动正常
powershell -ExecutionPolicy Bypass -File scripts\check_service_status.ps1 -Strict

# 3. Owner Console 可访问
# 浏览器打开 http://127.0.0.1:8000/owner

# 4. /web 可访问
# 浏览器打开 http://127.0.0.1:8000/web

# 5. Android 端 Pairing → 上传 → confirm 端到端验证
```

## 历史回滚点

- `v0.2.0-rc1` — v0.3 身份切换前的最后稳定点，已不再支持降级到此版本（identity_schema 已是 v0.3）
- 后续每个 minor 发布会打 `vX.Y.Z` tag；找最近 tag 用本文档顶部的"后端代码回滚"段
