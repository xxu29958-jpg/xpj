# v0.4-alpha4 — Android Emulator Acceptance Runbook

> 本轮真机不可用时的主验收路径。
> 真机验收见 [V0_4_ALPHA4_REAL_DEVICE_ACCEPTANCE.md](./V0_4_ALPHA4_REAL_DEVICE_ACCEPTANCE.md)。

## 环境

- AVD：API 34 Pixel 6（推荐）或任意 API ≥ 31 image
- 后端：`backend\run.bat`，监听 `127.0.0.1:8000`
- App flavor：`internalDebug`（强制走 `http://10.0.2.2:8000`）；勿用 gray flavor，否则会撞 production
- APK：`android\app\build\outputs\apk\internal\debug\app-internal-debug.apk`

## 准备

```powershell
cd E:\projects\xiaopiaojia\backend
.\run.bat

# 另一个终端
cd E:\projects\xiaopiaojia\android
.\gradlew.bat --no-daemon :app:assembleInternalDebug
adb -s emulator-5554 install -r app\build\outputs\apk\internal\debug\app-internal-debug.apk
```

## 验收清单

| # | 路径 | 期望 |
|---|---|---|
| 1 | App 启动 | 5 秒内进入待确认页，无 ANR |
| 2 | 配对 | 输入配对码后能成功绑定本地 backend |
| 3 | Pending 列表 | 显示种子数据，缩略图懒加载 |
| 4 | QuickCategory sheet | 选择分类 → 列表分类即时更新，sheet 关闭，toast "已更新分类" |
| 5 | QuickMerchant sheet | 输入空商家被拒；输入有效商家后保存成功 |
| 6 | MissingAmount sheet | 12.34 元 → 提交 1234 cents；保存草稿不确认；保存并确认离开列表 |
| 7 | BulkConfirm sheet | 缺金额跳过，疑似重复不被静默确认；统计 succeeded/failed/skipped |
| 8 | DuplicateConfirm sheet | "保留两笔" 调 markNotDuplicate；"忽略当前" 调 reject |
| 9 | Stats Reports | 月度、分类、最近 7 天卡片正常显示 |
| 10 | Ledger | 离线缓存可见上一次同步数据；筛选/导出入口正常 |

## 完成报告字段

```
Android validation: Emulator
Real-device validation: Pending
Emulator session: <date>
AVD: <name>
APK: app-internal-debug.apk (<commit-sha>)
Pass count: <n>/10
Notes: <issues>
```

## 已知约束

- gray flavor 指向 production `api.zen70.cn`；如必须用 gray，需 `adb reverse tcp:8000 tcp:8000` 并切到 production token，不在本 runbook 范围内
- emulator BiometricPrompt 行为不能代替真机：跳过该项验收
- emulator photo picker 选择系统图库 mock 图，不能验证真实拍照 → 真机验收覆盖
