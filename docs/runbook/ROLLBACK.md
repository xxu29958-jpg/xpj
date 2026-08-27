# 版本回滚 Runbook

本页主要提供源码/测试后端、Cloudflare Tunnel 与 Android 灰度的回退参考。当前正式 Windows 没有已出货的完整数据集恢复或二进制/schema 降级入口；以下源码命令不能冒充产品回滚能力。

## 适用范围与不可逆边界

回滚前必须先确认目标版本是否在"允许向下"范围内：

| 版本变更 | 是否允许回滚 | 说明 |
|---|---|---|
| 源码/测试后端补丁（同一 minor 内） | ⚠️ 逐项验证 | 代码可 `git revert`；数据库只允许 scratch 恢复演练 |
| Android 补丁（同一 minor 内） | ✅ 始终可逆 | 卸载灰度 APK，装上一版即可，Pairing 配对仍有效 |
| 正式 Windows 完整 generation 恢复 | ❌ 当前不可用 | Manager 不提供备份/恢复 mutation；该生命周期仍为 `HOLD` |
| 正式 Windows 二进制/schema 降级 | ❌ 不支持 | 不能用数据恢复绕过 release program 与运行态投影验证 |
| Android minor 降级 | ⚠️ 必须重新 Pairing | session token 在 Android 端 Keystore 中；旧 APK 不识别新 token，需重新配对 |
| **identity_schema 降级（任何方向越过 v0.3）** | ❌ 禁止 | `identity_schema=v0.3` 是 v0.3 以来的稳定契约；v0.3 之前的 `APP_TOKEN`/`UPLOAD_TOKEN` 模型已永久退役 |
| Cloudflare Tunnel 配置变更 | ✅ 可逆 | 保留上一版 `config.yml` 即可切回 |
| **数据库引擎（PostgreSQL，PG-only）** | ❌ 不可逆 | SQLite 已彻底退役；手工 `pg_restore` 只用于源码/测试 scratch 演练 |

## 源码/测试回退顺序

下列命令不适用于正式 Windows 安装：

1. **停服**：[scripts/stop_backend.ps1](../../scripts/stop_backend.ps1) 或 Windows 服务面板停止 ticketbox
2. **备份当前库**：避免回滚后悔时找不到现场（见下方"数据库备份与恢复"）
3. **代码切换**：`git checkout <旧 tag>`
4. **数据库 scratch 核对**（如需要，不覆盖正式库）
5. **重启**：[scripts/start_backend.ps1](../../scripts/start_backend.ps1)
6. **Android APK 回退**（如需要）：见 [RELEASE_PACKAGING.md](RELEASE_PACKAGING.md)
7. **网络入口回退**（如需要）：见 [CLOUDFLARE_TUNNEL.md](CLOUDFLARE_TUNNEL.md)
8. **验收**：见本文末"验收清单"

## 源码后端代码回退

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

### 回滚前数据留存

源码/测试环境按 [POSTGRES_MIGRATION.md](POSTGRES_MIGRATION.md) 在专用 scratch 数据库演练。正式 Windows 当前只能从产品内 `/web/import` 导出已确认流水 CSV；该文件不包含数据库、附件、身份或安装状态，不能称为完整备份。

### 恢复到某个备份

源码/测试 scratch 数据库可按 [POSTGRES_MIGRATION.md](POSTGRES_MIGRATION.md) 使用 `pg_restore`。正式 Windows Manager 当前不提供恢复入口；不得用“停后端 → 手工恢复 → 重启”绕过 Dataset Authority、Generation CURRENT 与运行态投影校验。

### 版本特定的数据库回滚注意

- **v0.9 → v0.8**：Reports/Goals/DashboardCard 表在 v0.8 代码中不会被读取，无需 drop；若希望干净环境可手工 drop，但**不要** drop budget 相关表（v0.8 仍读）
- **v0.8 → v0.7**：服务端 budget 表 v0.7 不读；同上，保留即可
- **v0.5 及以下**：已不支持，禁止回滚

## 数据库引擎不可逆（PG-only）

ADR-0041 把存储从 SQLite 换到本机 PostgreSQL，PG-only 瘦身后 SQLite 引擎/方言已**彻底退役**——没有 `DATABASE_URL=sqlite:///...` 回滚路径了。引擎层不可逆:

- 正式 Windows 完整恢复当前不可用并保持 `HOLD`；backend 恢复代码或 scratch 演练不是已出货产品入口。
- 历史背景见 [POSTGRES_MIGRATION.md](POSTGRES_MIGRATION.md) 与 ADR-0041(cut-over 2026-06-04 完成,SQLite 回滚源已失效)。

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
