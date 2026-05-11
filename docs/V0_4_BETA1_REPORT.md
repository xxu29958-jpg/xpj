# v0.4-beta1 家庭账本基础版 验收报告

- **分支**：`v0.4-beta1-family-ledger-foundation`（基线 tag `v0.4-alpha3-rc1`）
- **目标**：把小票夹从个人自用 RC 推进到“家庭私有账本”最小可用版（邀请 + 角色 + 不变量）
- **后端**：本地 `127.0.0.1:8000` + Cloudflare Tunnel `https://api.zen70.cn`
- **结论**：✅ 所有自动化门通过，可进入真机联调与小流量内测

---

## 1. 自动化验证矩阵

| 矩阵 | 命令 | 结果 |
|---|---|---|
| Backend bytecode | `python -m compileall backend\app` | ✅ OK |
| Backend lint | `ruff check backend` | ✅ All checks passed |
| Backend tests | `pytest backend\tests` | ✅ 325 passed in 324.65s |
| 文本编码 | `scripts\check_text_encoding.ps1` | ✅ UTF-8 / BOM 正常 |
| 全量入口 | `scripts\verify_project.ps1` | ✅ pass |
| Android unit | `:app:testGrayDebugUnitTest` | ✅ BUILD SUCCESSFUL |
| Android lint | `:app:lintGrayDebug` | ✅ BUILD SUCCESSFUL |
| Android assemble (gray) | `:app:assembleGrayDebug` | ✅ BUILD SUCCESSFUL |
| Android assemble (internal) | `:app:assembleInternalDebug` | ✅ BUILD SUCCESSFUL |

---

## 2. 交付清单（C1–C9）

| # | 主题 | 提交 |
|---|---|---|
| C1 | 设计文档 `docs/V0_4_BETA1_FAMILY_LEDGER_FOUNDATION.md` + 决策 `0022` | `94148b9` |
| C2 | `Invitation` ORM 模型 + `permission_service.py` + writer/owner-app 依赖 + 错误码 | `c747f4c` |
| C3 | `invitation_service.py` + `routes/invitations.py` + Schemas + `/api/expenses` 写入守卫 | `4ec9406` |
| C4 | 后端权限测试 `test_family_ledger_permissions.py`（20 场景） | `3efea88` |
| C5 | Owner Console 成员页（创建/撤销/禁用，明文一次性显示）+ 6 用例 | `2e01cd3` |
| C6 | `/web` 角色 chip + viewer 只读视图 + 4 用例 | `d2ff00f` |
| C7 | Android `JoinFamilyLedgerScreen` + `LedgerSwitcher` 角色 chip + 3 仓库测试（含 C8 的核心覆盖） | `17d21ad` |
| C8 | 邀请接受单测（覆盖成功、参数校验、服务端 4xx 三类） | 随 C7 合并 |
| C9 | `V0_4_BETA1_REAL_DEVICE_RUNBOOK.md` + 本报告 | （本提交） |

---

## 3. 关键设计与不变量

- **角色矩阵**：`owner` / `member` / `viewer`；`viewer` 写操作一律 403 (`viewer_cannot_write`)；admin scope 仅用于本机 Owner Console，**不绕过**只读边界（除明确的“成员管理”路径）。
- **邀请明文 (`inv_...`)**：`inv_` 前缀 + `secrets.token_urlsafe(24)`；DB 只存 SHA-256；明文仅在 Owner Console `POST /owner/ledgers/{id}/invitations` 响应中出现一次，绝不入库、不进 List 响应、不进日志。
- **TTL**：默认 7 天，最大 30；过期后接受返回 `invalid_invite_token`。
- **接受流程**（`POST /api/invitations/accept`）：**未鉴权**端点，单次创建新 `Account` + `Device` + `LedgerMember`，签发新 `AuthToken` 返回；不存在 token 重用或临时凭证。
- **跨账本枚举防护**：admin 越权访问陌生 ledger 的所有路由统一返回 `ledger_not_found` 404，**不是** 403（避免侧信道）。
- **隐私不变量（核心）**：家庭成员看不见 Owner 的个人账本；Owner 看不见家庭成员个人小票夹。`tests/test_family_ledger_permissions.py::test_joiner_does_not_see_owners_personal_ledger` 固化。
- **禁用即吊销**：`disable_member` 在同一事务内吊销目标成员该账本下所有 `AuthToken`；Android 端下一次同步将 401 并被引导回到绑定页。

---

## 4. 后端测试覆盖增量

| 文件 | 场景数 | 重点 |
|---|---|---|
| `tests/test_family_ledger_permissions.py` | 20 | 邀请生成 / 接受 / 撤销 / 过期 / 跨账本 / 隐私 / Viewer 403 |
| `tests/test_owner_console_members.py` | 6 | Owner Console 成员页所有路径（含一次性明文显示与列表脱敏） |
| `tests/test_web_role_badge.py` | 4 | `/web` 角色徽章 + Viewer 写按钮隐藏 |

`pytest` 总数从 alpha3-rc1 的 292 增长到 **322**（+30）。

2026-05-12 household hardening 后，新增 member/viewer 角色调整 API、Owner Console 表单和 3 个后端测试，`pytest` 总数增长到 **325**。

---

## 5. Android 端增量

- `data/remote/dto/LedgerDto.kt`：新增 `InvitationAcceptRequestDto` / `InvitationAcceptResponseDto`。
- `data/remote/ApiService.kt`：`@POST("api/invitations/accept") suspend fun acceptInvitation(...)`。
- `data/repository/LedgerRepository.kt::acceptInvitation`：trim + 长度校验（中文错误消息）→ 持久化新 token → `saveIdentity(Instant.now())` → `expenseDao.clearForLedger(...)` → `refreshLedgers()`；失败时**不**触碰任何本机状态。
- `ui/screens/settings/JoinFamilyLedgerScreen.kt`：三栏表单（邀请明文 / 显示名 / 设备名）+ 提交按钮 + 错误回显；接受成功后跳转到 `Ledgers` 路由并触发 `onLedgerSwitched()`。
- `ui/screens/settings/SettingsRoute.kt`：新增 `JoinFamilyLedger`。
- `ui/screens/settings/SettingsRootScreen.kt`：新增“加入家庭账本”入口 (`Icons.Filled.GroupAdd`)。
- `ui/screens/settings/LedgerSwitcherScreen.kt`：角色由纯文本升级为彩色 chip（owner 琥珀 / member 蓝 / viewer 灰），与 `/web` 一致。
- 单测 `LedgerRepositoryTest`：`acceptInvitationPersistsTokenIdentityAndWipesTargetCache` / `acceptInvitationRejectsBlankTokenWithChineseMessage` / `acceptInvitationServerErrorPreservesOldTokenAndBinding`。

---

## 6. 公网边界与隐私

- Owner Console 邀请管理路径全部在 `_require_local` 守卫下，公网访问 → 403。
- `/api/invitations/accept` 公网入口可达（与 `/api/auth/pair` 同级），需要正确的明文才能通过；脏 payload → 400 `invalid_payload`，错 token → 400 `invalid_invite_token`，过期 / 撤销 → 同样的统一错误码（避免区分泄漏）。
- 邀请明文不在 `/api/admin/*` 或任何 List 端点出现。

---

## 7. 已知限制 / 后续工作

| Id | 说明 | 计划 |
|---|---|---|
| L01 | 邀请未提供二维码/分享链接 | 沿用手工传递；v0.5 再考虑 |
| L02 | Owner Console 端的 member/viewer 角色调整 | 已作为 beta1 后续 hardening 补齐；owner 转让仍待 v0.5 |
| L03 | Member 无法在 App 内查看其他成员清单 | 仅 Owner Console 可见，按权限模型预期 |
| L04 | 接受邀请会替换本机当前绑定 | Runbook §4 提示用户先备份；后续考虑“多身份并存” |

---

## 8. 真机联调入口

详见 [`V0_4_BETA1_REAL_DEVICE_RUNBOOK.md`](V0_4_BETA1_REAL_DEVICE_RUNBOOK.md)。覆盖：

1. Owner 在 `/owner/ledgers/{id}/members` 派发邀请（一次性明文）。
2. 第二台 Android 设备在 设置 → 加入家庭账本 接受。
3. 角色边界验证（成员可写 / 只读 403 / 隐私不可见性）。
4. Owner 禁用 / 撤销路径。
5. 故障速查与已知限制。
