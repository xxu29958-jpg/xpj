# v0.4-alpha3 RC1 Known Issues

基线：commit `c05e85f`（main, 2026-05-11）

## P0（必须修复才能 GA）

无。

## P1（必须修复或明确豁免才能打 RC1 tag）

无。

## P2（不阻塞 RC1，下一版可改）

### P2-1：`test_admin_devices_and_upload_links.py` 全量顺序下偶发 5 条排序 flake

- **现象**：`verify_project.ps1` 跑全量 pytest 时，`test_admin_devices_and_upload_links.py` 中 5 条 case 可能因测试顺序失败；单独跑该文件 14/14 全 pass，main 和 slice3 分支均存在。
- **判定**：测试间共享 fixture 状态导致的排序敏感，与 v0.4-alpha3 改动无关，是历史 debt。
- **影响**：CI 上偶发红，本地隔离运行可复现 14/14 绿。
- **后续**：在 `docs/ANDROID_DEBT_BACKLOG.md` 同级建一个 backend debt 条目（v0.5 处理）。

### P2-2：账本创建必须联网（设计契约）

- **现象**：在 Android 端"设置 → 账本（实验）→ 新建账本"如果当前无网络，会失败。
- **判定**：**这是设计契约，不是缺陷**。账本 ID 必须由服务端权威分配，owner 凭证必须由服务端签发，否则会破坏 `(device_id, account_id, ledger_id)` 三元组隔离与 token 体系。
- **现状**：读路径（账本列表 / 账单 / 统计）**已支持离线缓存**，写路径中"补金额/备注/分类"也走本地优先，**仅"新建账本"和"切换账本"需联网**。
- **后续 v0.5**：考虑 local-first ledger creation（客户端临时 UUID + 服务端 reconcile + 冲突 UI）。代价：Room migration + 身份系统改造 + 新增 reconcile 接口，须等接口稳定窗口。

### P2-3：BiometricPrompt 无法通过 adb 自动化验证

- **现象**：真机解锁使用 BiometricPrompt（BIOMETRIC_STRONG | DEVICE_CREDENTIAL），`adb shell input tap` 无法触发指纹/面容验证。
- **判定**：Android 平台限制，无法绕过；BiometricPrompt 是系统级 overlay，`uiautomator dump` 也不可见。
- **影响**：CI 真机自动化无法跑通完整 UX；RC 验收时需人工指纹/PIN（PIN 258036 是 fallback）。
- **后续**：本地 debug 构建已支持开关，若需 CI 全自动化可在 `internalDebug` flavor 上加 `BiometricPromptStub`（不引入新功能，仅测试钩子）。

### P2-4：公网边界脚本默认 BaseUrl 为占位符

- **现象**：`scripts\check_public_boundary.ps1` 和 `check_selfuse_health.ps1` 默认 `-BaseUrl https://api.example.com`（占位）。不传参直接跑会全 530。
- **判定**：刻意设计——避免真实域名进仓。
- **后续**：在 `scripts/README.md` 或 `docs/CI.md` 顶部明确"必须 `-BaseUrl https://<your-domain>`"，并将常用调用方式记入 `AGENTS.md`。

## 非阻塞观察项

- 隧道计划任务 `TicketboxCloudflareTunnel` 不会随 Windows 启动自动 Running（在 Ready 状态），需手动 `Start-ScheduledTask` 或重启后才会被调度。建议在 `docs/CLOUDFLARE_TUNNEL.md` runbook 顶部加一条"重启 / 长时间未用后先检查任务状态"。
- 多账本切换时若隧道刚 down，UI 显示"刷新中..."几秒后会回退到本地缓存——体验良好，无 P-issue。
