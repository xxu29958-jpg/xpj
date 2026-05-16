# 版本真值源

本文件是小票夹"版本号"的唯一权威来源。任何 README、API、CI、运维脚本若需引用版本，必须以本文件为准，并保持与下表的代码位置同步。

## 当前版本

| 维度 | 版本 | 代码位置 |
|------|------|----------|
| 后端 `BACKEND_VERSION` | `0.9.0a1` | [backend/app/version.py](../backend/app/version.py) |
| 后端 `IDENTITY_SCHEMA_VERSION` | `v0.3` | [backend/app/version.py](../backend/app/version.py) |
| Android `versionName` | `0.9.0a1` | [android/app/build.gradle.kts](../android/app/build.gradle.kts) |
| Android `versionCode` | `90000` | [android/app/build.gradle.kts](../android/app/build.gradle.kts) |

> Android internal 构建会自动追加 `-internal` 后缀；正式发布请走 release 配置。

## 阶段标签

- v0.9.0a1：Reports / Goals / Dashboard 卡片配置 + Vico 图表 + `/web` ECharts 收口。
- 下一里程碑：v1.0 后端数据能力地基（商品级小票、家庭拆账、10k CSV、v0.x→v1.0 迁移/回滚工具）。

## 版本号约束

- `BACKEND_VERSION` 与 Android `versionName` 必须始终保持完全一致字符串。
- Android `versionCode` 与 `versionName` 的映射规则：`MAJOR * 10_000_000 + MINOR * 100_000 + PATCH * 1_000 + (alpha/beta 序号)`。当前 `0.9.0a1 → 90000`。
- `IDENTITY_SCHEMA_VERSION` 只在 Account / Ledger / Device / AuthToken / UploadLink / PairingCode 契约变更时升级；v0.9 不动。
- 发布新版本时，**只改 [backend/app/version.py](../backend/app/version.py) 与 [android/app/build.gradle.kts](../android/app/build.gradle.kts) 顶部的 `ticketboxVersionCode` / `ticketboxVersionName`，然后同步更新本文件与 [README.md](../README.md) 的"当前版本"段落**。其它脚本与文档不应硬编码版本字符串。

## 校验

合入前手动核对：

```powershell
# 后端
Select-String -Path backend\app\version.py -Pattern 'BACKEND_VERSION'
# Android
Select-String -Path android\app\build.gradle.kts -Pattern 'ticketboxVersionName'
# 文档
Select-String -Path docs\VERSION.md -Pattern '当前版本'
Select-String -Path README.md -Pattern '当前版本'
```

四处字符串必须一致。
