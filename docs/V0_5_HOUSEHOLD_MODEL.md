# v0.5 Household 权限模型

日期：2026-05-13

范围：v0.5 只收紧家庭账本权限、成员管理、只读体验和版本标识；不改金额、时间、图片、Room schema 或身份 schema。`identity_schema` 仍为 `v0.3`。

## 1. 角色模型

| 角色 | 可读账单 | 可写账单 | 可管理成员 | 可创建邀请 | 可转让 owner |
| --- | --- | --- | --- | --- | --- |
| 拥有者 `owner` | 是 | 是 | 是 | 是 | 是 |
| 成员 `member` | 是 | 是 | 否 | 否 | 否 |
| 只读 `viewer` | 是 | 否 | 否 | 否 | 否 |

三端统一显示为：拥有者、成员、只读。

## 2. 写入口约束

`viewer` 统一返回：

```json
{"error":"permission_denied","message":"当前角色为只读，无法修改账本。"}
```

后端强制点：

- Android 上传：`POST /api/app/upload-screenshot`
- 手动记账、编辑、确认、拒绝等账单写入口
- 分类规则 create/update/delete/apply-pending
- `/web` 直接 POST：save、confirm、reject、bulk、rules、import confirm、categories、duplicates

模板隐藏按钮只做体验；真正拒绝在后端完成。

## 3. 邀请和接受

- 邀请只能由当前账本 owner 创建。
- 邀请角色只能是 `member` 或 `viewer`，不能通过邀请创建 owner。
- 邀请明文只在创建响应或 Owner Console 创建页显示一次。
- 数据库只保存邀请 token hash，不保存明文。
- Android 接受前先调用 preview，展示目标账本名、邀请角色和当前绑定。
- preview 不消费邀请；accept 成功后才替换本机 session token 和当前账本绑定。
- accept 失败不得覆盖旧 token、旧账号、旧账本或旧角色。

## 4. 成员管理

Owner Console 成员页支持：

- 查看当前账本成员、角色、加入时间、停用状态。
- 将活跃非 owner 成员在 `member` / `viewer` 间调整。
- 停用活跃非 owner 成员，并吊销该成员在当前账本的活跃 token。
- 将 owner 显式转让给一个活跃非 owner 成员。

Owner 转让规则：

- 始终保持单 owner。
- 事务内完成新 owner 提升、旧 owner 降级、`Ledger.owner_account_id` 更新和审计记录。
- 不能转让给自己、停用成员、未知成员或当前 owner。
- 转让后旧 owner 的既有 token 下次鉴权立即体现为 `member`，新 owner 立即可管理成员。

## 5. 审计

家庭成员审计按账本记录：

- 创建邀请
- 接受邀请
- 撤销邀请
- 调整角色
- 停用成员
- 转让 owner

审计不得记录：

- 邀请明文 token
- session token / admin token
- UploadLink 明文
- Windows 本机真实路径

## 6. 导入导出决策

- `viewer` 可以导出已确认账单 CSV，因为它已经有读取账本的权限。
- `viewer` 不能确认 CSV import，也不能通过 `/web/import/confirm` 写入账单。
- import preview 仍是本机页面体验，不等同于写入。

## 7. 老库兼容和回滚

老库兼容：

- `LedgerMember.role` 约束为 `owner/member/viewer`。
- `Invitation.role` 约束为 `member/viewer`。
- 启动迁移会补齐约束策略，并保留既有身份 schema。

回滚原则：

- 回滚代码前先备份 `backend/data/ticketbox.db`。
- 已写入的 `viewer`、审计和邀请记录应保留；旧版本如果不理解这些入口，不应继续执行家庭成员管理。
- 如果必须回退到 v0.4-beta1 行为，先停止后端，恢复 v0.5 之前的数据库备份，再启动旧代码。

## 8. 验证快照

当前 v0.5.0a1 验证过：

- 后端全量 pytest：340 passed。
- 后端 smoke：通过。
- Android `testGrayDebugUnitTest`：通过。
- Android `assembleGrayDebug` / `assembleInternalDebug` / `assembleGrayRelease` / `assembleInternalRelease` / `lintGrayDebug`：通过。
- 真机安装：`versionName=0.5.0a1`，`versionCode=50000`。
