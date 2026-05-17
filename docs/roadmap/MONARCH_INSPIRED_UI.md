# Monarch-inspired UI（信息架构参考说明）

> 参考的是**信息架构**，不是品牌。本文记录小票夹从 v0.4-alpha2 起从
> Monarch Money 借鉴了哪些产品组织范式，以及**明确不借鉴**的部分。

## 借鉴的部分

仅限信息组织范式，不复制视觉与功能：

- **Dashboard**：把首页做成生活流卡片网格，而不是工程列表。
- **Transactions Review**：把“需要人工处理”集中到一个 Review Inbox 入口，
  而不是和已确认账单混在一起。
- **Transaction row**：商家 → 金额 → 分类 → 时间 → 来源 → 状态 这一稳定
  字段顺序，三端一致。
- **Reports Cards**：用一组轻量卡片表达本月支出、分类排行、最近确认、
  大额支出，而不是堆复杂报表。
- **Recurring 思路**：以“固定支出”这一概念给用户一个未来的去处，但本期
  只放 placeholder。
- **Household 信息架构**：账本区分为“个人 / 共享”，v0.4-beta1 已落地
  邀请、member/viewer 和隐私隔离基础，但权限模型反向 Monarch。
- **三端一致体验**：手机 / 桌面 / 管理后台共享同一套信息顺序与状态词。
- **三端视觉统一**：三端不强行复刻同一布局，但共享颜色语义、卡片节奏、
  状态 badge、空状态、加载态、错误态和生活化中文文案。

## 不借鉴

明确不复制、不集成、不暗示已具备的能力：

- **不复制 Monarch 商标、配色、文案、图标、素材或代码**。
- **不接银行 / 信用卡 / 经纪商账户**；小票夹只接受截图上传。
- **不做净资产 / 投资 / 资产负债表**。
- **不做付费金融数据聚合**（Plaid / Finicity / MX 等）。
- **不做自动入账**：上传只创建 pending，OCR 只填草稿，确认仍是手动。
- **不做 Monarch 式 household 全账户可见**；成员只能看到自己账本和被显式邀请的共享账本。
- **不做真实预算 / rollover / 推送通知 / shared views / bill sync**。

## 小票夹自己的翻译

文档与 UI 文案统一使用小票夹术语，不直接搬 Monarch 用词：

| Monarch 概念 | 小票夹术语 |
| ------------ | ---------- |
| Accounts     | 截图上传（iPhone UploadLink / Android / 手动 / Web） |
| Transactions | 账单（pending / confirmed / rejected） |
| Review       | 待确认（Needs Review） |
| Ledgers      | 账本（个人账本 / 家庭账本） |
| Households   | 共享账本 / 家庭账本（显式邀请，不共享个人账本） |
| Devices      | 设备 |
| Backups      | 备份 |
| Reports      | 报表（本月支出 / 分类排行 / 最近确认 / 大额支出） |

## 范围边界（提醒）

- v0.4-beta1 后，小票夹仍**没有**：自动同步银行、自动入账、Monarch 式全账户家庭共享、
  真实预算、真实 recurring、跨账本统计、`/web` 公网开放。
- 任何 placeholder 文案必须显式写明“当前不会自动判断 / 当前不会自动扣预算 /
  当前不会自动入账”。

## 后续 UI/UX 统一

`v0.8` 以后，预算、统计、报表和 Dashboard 会进入主体验。三端 UI/UX polish
必须同时覆盖 Android、`/web` 和 `/owner`，但保持各自定位：

- Android：生活化、触摸优先、少打扰。
- `/web`：桌面账本效率、批量处理、报表浏览。
- `/owner`：本机管理和运维状态，仍只允许 loopback。

统一政策见 `docs/DECISIONS/0024-tri-surface-ui-ux-unification.md`。
