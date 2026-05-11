# v0.4-alpha4 — Android Real-Device Acceptance Runbook

> RC 阶段必跑。alpha4 本轮可标记 Pending，但 runbook 必须在仓。

## 适用设备

- Xiaomi 2410DPN6CC（已在册的开发用机，serial `c16cd054`）
- 任意 Android 12+ 真机；biometric / photo picker 行为需以系统实测为准

## 前置

| 项 | 要求 |
|---|---|
| ADB 调试 | 已授权 |
| 屏幕锁 PIN | 已记录（开发机：258036） |
| 后端 | gray 走 `api.zen70.cn` 生产域名；internal 走 `http://<本机内网 IP>:8000` |
| Cloudflare tunnel | 仅 gray flavor 在外网用 |
| APK | `app-grayDebug.apk` 或 `app-internalDebug.apk` |

## 安装

```powershell
cd E:\projects\xiaopiaojia\android
.\gradlew.bat --no-daemon :app:assembleGrayDebug   # 走生产
# 或
.\gradlew.bat --no-daemon :app:assembleInternalDebug # 走本地 backend，需 adb reverse
adb -s c16cd054 install -r app\build\outputs\apk\<flavor>\debug\app-<flavor>-debug.apk
```

如使用 internal flavor：

```powershell
adb -s c16cd054 reverse tcp:8000 tcp:8000
```

## 验收清单

### A. 基础体验

| # | 路径 | 期望 |
|---|---|---|
| A1 | 冷启动 | < 3 秒进入待确认 |
| A2 | BiometricPrompt | 指纹 / 面容解锁正常；取消后 fallback PIN |
| A3 | Photo Picker | 系统相册返回真实图片，类型与字节数与 backend 接收一致 |
| A4 | 上传截图 | 进度条 → 成功 → pending 列表新增 |
| A5 | OCR 状态 | 等待 OCR 结果时不阻塞 UI |

### B. Review Workflow（slice 3 主路径）

| # | 路径 | 期望 |
|---|---|---|
| B1 | QuickCategory | sheet 打开 → 选择 → 列表分类更新 |
| B2 | QuickMerchant | 空商家被拒；trim 后保存成功 |
| B3 | MissingAmount 保存草稿 | PATCH 后金额生效，但仍在 pending |
| B4 | MissingAmount 保存并确认 | PATCH 后 confirm，离开 pending |
| B5 | BulkConfirm | 缺金额跳过；疑似重复不被静默确认 |
| B6 | DuplicateConfirm 保留 | markNotDuplicate；不再标记为 suspected |
| B7 | DuplicateConfirm 忽略 | reject；离开列表 |

### C. 周边

| # | 路径 | 期望 |
|---|---|---|
| C1 | Stats Reports | 月度、最近 7 天、Top 商家、frequent merchants 正确 |
| C2 | Ledger 离线缓存 | 网络断开仍能看到上次同步 |
| C3 | Cloudflare tunnel | gray flavor 在外网网络下能访问 |
| C4 | iPhone UploadLink | iPhone 通过 web upload link 上传后，安卓 App pending 出现 |
| C5 | 长期使用 | 1 小时连续操作无 OOM / ANR |

## 已知阻塞（截至 alpha4 开工）

- 本地 backend 是 v0.3.x，无 slice 3 endpoint；gray flavor 绑定 production，本地无法用 gray 走完 review workflow
- 真机灰度需要 production server 升级到至少 v0.4-alpha3-rc1 后端 → **真机验收推迟到 RC 阶段，alpha4 标记 Pending**

## 报告模板

```
Real-device validation: <Pass|Pending|Fail>
Device: Xiaomi 2410DPN6CC (c16cd054)
APK: app-<flavor>-debug.apk (<commit-sha>)
Session date: <date>
Pass count: <n>/17
Blocked items: <list with reason>
Logcat: artifacts/screenshots/rd_<date>_logcat.txt
Screenshots: artifacts/screenshots/rd_<date>_*.png
```
