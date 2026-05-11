# v0.4-beta1 家庭账本真机联调 Runbook

本文档用于在 `v0.4-beta1-family-ledger-foundation` 分支上验证家庭账本邀请、接受、角色枚举的端到端链路。前置条件请参见 [REAL_DEVICE_RUNBOOK.md](REAL_DEVICE_RUNBOOK.md)（基础联调步骤未变）。

> 边界：邀请明文 (`inv_...`) 只在 Owner Console 创建时返回一次，绝不入库、不进日志。本机管理后台始终只在 127.0.0.1 上可达。

---

## 1. 测试角色与设备

| 角色 | 设备 | 备注 |
|---|---|---|
| Owner | Windows + 现有 Android 设备 c16cd054 | 拥有 `Owner` 自有账本与新建的 `家庭账本` |
| Member | 第二台 Android 设备（实机/模拟器均可） | 通过邀请明文加入 |
| Viewer | 同上，单独邀请 | 验证只读边界 |

Owner 与 Member 使用各自独立的 Account；这是设计要求：家庭成员不会看到对方的个人账本（反向 Monarch 不可见性）。

---

## 2. 启动后端 + 隧道

```powershell
cd E:\projects\xiaopiaojia\backend
.\run.bat
```

确认 `https://api.zen70.cn/api/health` 200。

公网边界自检（35/35 PASS）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check_public_boundary.ps1 -BaseUrl https://api.zen70.cn
```

---

## 3. Owner 端：创建家庭账本 + 邀请

1. 浏览器打开 `http://127.0.0.1:8000/owner/ledgers`（仅 loopback 可达）。
2. 在“账本”页面点击“新建账本”，输入名称 `家庭账本`。
3. 在新账本行点击“成员/邀请”，进入 `/owner/ledgers/{ledger_id}/members`。
4. 在“创建邀请”表单：
   - 角色：`成员（可写）` 或 `只读`
   - 备注（可选）：≤80 字
   - 有效期（天）：默认 7，可改为 1–30
5. 提交后顶部绿色卡片显示一次性邀请明文（`inv_` 开头）。**立即拷贝**，关闭页面后不会再次出现。
6. （可选）在 `/web/pending`、`/web/stats` 等页面确认本机 Owner 视图正常，角色徽章显示“所有者”，无只读警告。

---

## 4. Member 设备：加入家庭账本

1. 确保设备已通过常规 PairingCode 流程绑定本机的服务端（任意账本均可，邀请接受会替换当前绑定）。
2. 在 App 内：设置 → “加入家庭账本”。
3. 填入：
   - 邀请明文：粘贴第 3 步拷贝的 `inv_...`
   - 你的显示名：例如 `家人 A`
   - 设备名：例如 `Pixel 8`
4. 点击“接受邀请”。
5. 期望：
   - Toast/消息提示：`已加入"家庭账本"，当前角色：member`
   - 自动跳转到“账本”页，新账本带蓝色 `成员（可写）` 角色 chip，且为“当前”。

如果服务器返回错误：

| 错误关键字 | 中文消息 | 处理 |
|---|---|---|
| `invalid_invite_token` | 邀请已过期或不存在 | 让 Owner 重新创建邀请 |
| `ledger_member_disabled` | 该成员已被禁用 | Owner 需重新创建邀请（旧邀请已废） |

App 端：失败时本机 Token 不被覆盖，原绑定不受影响。

---

## 5. 角色边界自检（Member）

| 场景 | 期望 |
|---|---|
| 切换到 `家庭账本` | 顶栏角色 chip = 成员（可写） |
| `/web` 视图（用 Member 的 token） | 角色 chip = 成员（可写），无只读警告，可写按钮可见 |
| 在 App 内新增/编辑费用 | 成功 |
| 服务器 `/api/expenses` POST 检查 | 200 OK |

切到 Viewer 邀请重复上述：

| 场景 | 期望 |
|---|---|
| Viewer 加入后 `/web` 顶部 | 黄色只读警告横幅 + 灰色 `只读` chip |
| App 内尝试新增费用 | 服务器返回 `viewer_cannot_write` 403 |
| 服务器 `/api/expenses` POST | 403，App 显示 `当前角色为只读，无法修改账本` |

---

## 6. Owner：撤销 / 禁用

1. 回到 `/owner/ledgers/{id}/members`。
2. 在 `成员` 表对该 Member 点击“禁用”：该成员所有 AuthToken 同步撤销，下一次 API 请求 401。
3. 在 `邀请` 表对未使用的邀请点击“撤销”：邀请立刻不可接受（即使在 TTL 内）。
4. 已接受过的邀请不会撤销已建立的成员；要切断已加入的成员请用第 2 步。

---

## 7. 隐私不变量（关键）

Owner 名下的“个人小票夹”账本对家庭成员不可见：

- Member 设备的 `/api/ledgers` 列表中**不会**出现 Owner 的个人账本，只有共同的 `家庭账本`。
- 通过手工凑出 Owner 个人账本 `ledger_id` 直接访问，会返回 `ledger_not_found` 404（而非 403），避免枚举侧信道。

后端测试 `tests/test_family_ledger_permissions.py::test_joiner_does_not_see_owners_personal_ledger` 固化此约束。

---

## 8. 故障速查

| 现象 | 原因 / 处理 |
|---|---|
| Owner Console 公网可达 | 立即检查 `selfuse_health` H06；正常应 403 |
| App 接受邀请提示“账本地址未绑定” | 设备从未配对过；先走 PairingCode 流程 |
| 邀请明文复制后丢失 | 必须重新创建邀请，不可找回 |
| 禁用的成员仍能拉到数据 | 检查后端日志确认 `disable_member` 是否抛错；正常情况下原子事务一次性吊销 Token |

---

## 9. 已知限制（v0.4-beta1）

- 邀请明文只通过本机 Owner Console 派发，没有公网入口。
- 邀请明文不提供二维码/分享链接，需要手工传递（短信/聊天/纸条均可）。
- Member 只能加入一个邀请到当前设备；若需要切回个人账本，可在 App `账本` 页用账本切换。
- 角色变更（升降级）暂未在 Owner Console 暴露 UI，需要管理员通过 `/api/admin/*` 操作。
