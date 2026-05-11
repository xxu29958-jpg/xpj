# v0.4-alpha3 RC1 截图与产物索引

所有产物存放在 `artifacts/v0_4_alpha3_rc1/`，该目录被 `.gitignore` 排除，不入仓。本索引仅记录文件清单与说明。

## Android 真机截图

| 文件 | 说明 | 大小 |
|---|---|---|
| `D1_settings.png` | 解锁后设置 Tab 根页（owner 角色 / 当前账本 / 连接中 / 最近上传） | 957 KB |
| `D2_pending.png` | 待确认 Tab（隧道未恢复时显示"连接出错 530"+ 缓存空状态）| 1136 KB |
| `D3_ledger.png` | 账本 Tab（离线优先：2026年5月 合计 ¥3547.58 / 3 笔）| 1048 KB |
| `D4_stats.png` | 统计 Tab（含"已显示本机账本统计，联网后会自动更新"+ 分类集中度）| 1208 KB |
| `D5_expense_detail.png` | 确认/编辑详情（OCR 草稿 ¥38 / 待填写商家 / 疑似重复提示 / 分类 chips）| 998 KB |
| `D6_settings_full.png` | 设置完整列表（账本连接 / 外观与主题 / 分类规则 …）| 957 KB |
| `D7_ledger_switcher.png` | 多账本切换器（默认账本 + 家庭账本 + 新建账本 UI）| 1148 KB |
| `D8_stats_detail.png` | 统计 Tab 二次访问（验证导航稳定）| 828 KB |
| `android_post_tunnel.png` | 隧道恢复 + iPhone 上传后整体 App 状态 | 1176 KB |
| `F1_multiledger_realdevice.png` | F 段终态：7 张待确认（含 iPhone 上传项）+ 多账本隔离生效 | 见目录 |
| `android_after_tap.png` | BiometricPrompt 唤起瞬间（指纹 overlay 仅在屏幕截图可见，uiautomator dump 不可见）| — |
| `android_current.png` | 解锁后第一帧 | 957 KB |
| `android_launch.xml` / `android_unlock.xml` / `D*.xml` / `F1*.xml` | 各步骤 uiautomator dump | — |

## 日志

| 文件 | 说明 |
|---|---|
| `backend_pytest.log` | 292 passed in 265.21s |
| `backend_smoke.log` | recognize / confirm / csv / duplicates / rules / auto-classification 全 OK |
| `android_gates.log` | testGrayDebugUnitTest + assembleGrayDebug + assembleInternalDebug + lintGrayDebug 全 SUCCESS |
| `public_boundary.log` | 35/35 PASS（使用 `-BaseUrl https://api.zen70.cn`） |
| `public_boundary_v2.log` | 13/35（不传 BaseUrl 时的占位域名结果，仅作对照） |
| `selfuse_health.log` | 11/11 OK |
| `owner_root.html` | `/owner/` 根页 HTML 快照 |

## 后续清理

- 真机调试完成后可整体删除 `artifacts/v0_4_alpha3_rc1/`，所有信息已收纳进本文档 + REPORT + KNOWN_ISSUES。
- 如需重现，按 `docs/V0_4_ALPHA3_RC1_REPORT.md` 第 1-5 节命令即可。
