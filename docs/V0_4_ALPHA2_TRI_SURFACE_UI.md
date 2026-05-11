# v0.4-alpha2 Monarch-inspired Tri-surface UI/UX

> 状态：**进行中**。基线 = main `5a9e18b`（PR #11 已合并，v0.4-alpha1 多账本地基）。
> 身份契约保持 `identity_schema=v0.3`，不改 Account / Ledger / Device / AuthToken /
> UploadLink / PairingCode 表，也不改 Room schema version。

## 目标

把小票夹从“功能接起来”推进到“产品形态清楚”。三端共用同一套信息顺序、同一套
状态词、同一套空状态文案，但保留各自定位：

- **Android = 生活流**：首页升级为 Dashboard + Needs Review 收件箱，
  围绕“截图 → 待确认 → 已确认账单”做生活化呈现，不是工程列表。
- **/web = 桌面账本流**：本机桌面版 Review Center + Transaction Center +
  轻量 Reports；顶部加 ledger selector，按账本切换 pending / confirmed /
  stats / edit / confirm / reject。
- **/owner = 本机管理流**：服务状态、设备、上传链接、账本、备份、诊断分区
  清楚，不再像散页脚本。仍只允许 loopback。

## 不做

- 不改身份 / Ledger / Device / AuthToken / UploadLink / PairingCode 表契约。
- 不改 Room schema version；不增加 `fallbackToDestructiveMigration`。
- 不引入 React / Vue / Svelte / Node 前端框架，也不引入复杂图表库。
- 不做家庭成员邀请、成员隐私隔离、角色变更 UI、归档 / 删除 / 转让。
- 不做真实预算、真实 recurring 算法、真实 rollover、真实 shared views、
  真实 bill sync。
- 不做银行 / 信用卡 / 投资 / 净资产聚合，不复制 Monarch 品牌、视觉素材、
  文案或付费金融能力。
- 不开放 `/owner` 或 `/web` 到公网；公网仍 403。
- Android 普通用户主体验不显示 `serverUrl` / token / endpoint / Cloudflare /
  端口 / 接口名 / pairing code 历史值。
- HTML 模板不渲染 `token_hash` / `upload_key` / pairing code / 绝对路径。

## 三端共同字段顺序（交易卡）

```
缩略图  →  商家  →  金额  →  分类 badge  →  时间  →  来源  →  状态  →  账本
```

- 缩略图为空时显示生活化文案（“图片已保存”/“暂不预览”/“已清理”）；
- 商家为空显示“未填写商家”；
- 金额为空显示“待填写金额”（仅 pending；confirmed 必须有金额）；
- 来源：iPhone / Android / 手动 / Web；
- 状态词见下一节。

## 三端共同状态词

```
待确认 · 缺金额 · 缺商家 · 疑似重复 · 已确认 · 已忽略 · 离线 · 备份过期 ·
设备正常 · 设备已停用
```

详见 `docs/TRI_SURFACE_INFORMATION_ARCHITECTURE.md`。

## 不变的安全 / 隔离防线

- Android 切换账本仍走 `POST /api/ledgers/{id}/switch`，
  `LedgerRepository.switchLedger` 顺序不变：保存新 token → 写 active ledger
  → `clearForLedger(targetId)`。
- ExpenseDao 的 `findAnyByServerIds` + claim-legacy 语义保持不动；
  Dashboard 改造**不得**绕过 ledger 维度过滤。
- `/web` 选中账本必须经过 `_resolve_selected_ledger_id` 这层服务端 validate，
  只能选 owner 可见账本，绝不接受任意 `ledger_id` query。
- `/owner` 与 `/web` 公网仍 403；Owner Console 仍 loopback only。
- 上传只创建 pending、OCR 只填草稿、重复检测只提示、用户确认才 confirmed。

## 验收

详见合同 Phase 8 + Phase 11。除三端真机/桌面截图外，必须保证：

- backend `pytest` 全绿，含新增 `/web` selected ledger 隔离测试与
  `/owner` 不泄漏字段测试；
- Android 单元 / assemble / lint 全绿；
- `scripts/verify_project.ps1` / `check_text_encoding.ps1` / `check_public_boundary.ps1`
  全绿；
- 切换账本后 pending / confirmed / stats / 本地缓存 / token 不串。
