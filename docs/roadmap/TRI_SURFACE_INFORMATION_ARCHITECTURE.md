# 三端信息架构（Tri-surface Information Architecture）

> v0.4-alpha2 起，小票夹 Android、`/web`、`/owner` 三端共用这一套信息顺序、
> 状态语言与空状态文案。本文档**直接**指导 Android Compose、`/web` Jinja
> 模板与 `/owner` Jinja 模板的施工。

## 三端定位

| Surface | 定位 | 入口 |
| ------- | ---- | ---- |
| Android | 生活流（Dashboard + Needs Review Inbox） | App 底栏“待确认” / “账本” |
| `/web` | 桌面账本流（Review Center + Transaction Center + 轻量 Reports） | 本机浏览器 `http://127.0.0.1:8000/web` |
| `/owner` | 本机管理流（服务 / 设备 / 上传链接 / 账本 / 备份 / 诊断） | 本机浏览器 `http://127.0.0.1:8000/owner` |

`/web` 与 `/owner` 均 loopback only，公网仍 403。

## 共同信息顺序

### 交易卡 / 行字段顺序

```
1. 缩略图           image / placeholder
2. 主标题：商家      未填写商家 / merchant
3. 主金额           ¥xxx.xx / 待填写金额
4. 分类 badge       例：餐饮 / 交通 / 购物 / 未分类
5. 时间             消费时间 || 创建时间（短格式）
6. 来源             iPhone / Android / 手动 / Web
7. 状态             待确认 / 缺金额 / 缺商家 / 疑似重复 / 已确认 / 已忽略
8. 账本             仅当跨账本上下文必要时显示（账本名 + “个人/家庭”）
```

### 简卡 / 设备 / 账本 / 备份字段顺序

```
1. 主标题：设备名 / 账本名 / 备份文件名
2. 主指标：状态 / 数量 / 大小
3. 辅助：角色 / 时间 / 设备型号
4. 状态：正常 / 已停用 / 过期 / 离线 / 备份过期
```

## 共同状态词

三端 UI / 文案统一使用下列词汇，不再各自翻译：

| 状态 | 含义 | 来源 |
| ---- | ---- | ---- |
| 待确认 | pending 且字段齐全 | 服务端 status=pending |
| 缺金额 | pending 且 `amount_cents` 为空 | 本地派生 |
| 缺商家 | pending 且 `merchant` 为空 | 本地派生 |
| 疑似重复 | `duplicate_status == "suspected"` | 服务端 |
| 已确认 | confirmed | 服务端 status=confirmed |
| 已忽略 | rejected | 服务端 status=rejected |
| 离线 | 网络异常 / 仅本地缓存 | Android `lastConfirmedSyncAt` / 网络 state |
| 备份过期 | 最近一次备份 > 7 天 | `selfuse_health` H10 |
| 设备正常 | 设备未 revoked | Owner Console |
| 设备已停用 | 设备 `revoked_at != null` | Owner Console |

## 共同空状态文案

| 场景 | 文案 |
| ---- | ---- |
| 没有待确认 | 今天还没有截图待确认 |
| 没有已确认 | 这个月还没有已确认账单 |
| Reports 无数据 | 还没有可统计的数据，确认后才会出现 |
| 离线只能看缓存 | 暂时离线，正在显示本地缓存 |
| 账本暂无图片 | 图片已保存 / 暂不预览 / 已清理 |
| 预算 placeholder | 预算功能会在后续版本开启 |
| Recurring placeholder | 可能是固定支出的消费，后续会在这里提醒 |
| 家庭成员空状态 | 当前账本还没有家庭成员 |

## 共同分类 badge

三端分类 badge 以服务端 / Android 默认分类为准，至少覆盖下列基础类，并以“未分类”兜底：

```
餐饮 · 交通 · 购物 · 居家 · 娱乐 · 医疗 · 教育 · 住房 · 通讯 · 其他 · 未分类
```

颜色三端一致（CSS 变量与 Compose 主题色一一对应），在视觉系统文档中定义。

## Android：生活流

`PendingScreen` 升级为 Dashboard + Needs Review。

### Dashboard 卡片（顺序）

1. **当前账本卡** — `LedgerContextPill`：账本名 + “个人 / 家庭”徽标。
2. **本月已确认** — 来自 `lifestyleStats` / `monthlyStats`，无数据显示
   “这个月还没有已确认账单”。
3. **待确认截图** — pendingCount。
4. **需要补金额** — pending 中 `amount_cents` 为空的数量。
5. **疑似重复** — `duplicate_status == "suspected"` 的数量。
6. **本月最多分类** — 来自 `lifestyleStats.topCategory`。
7. **最近上传** — `settingsStore.lastUploadAt()`。
8. **同步状态** — `lastConfirmedSyncAt()` / 离线徽标。

所有数字必须来自真实 state / stats / settings，**不得**生成假数据。

### Needs Review filter（本地 UI 筛选，不改后端字段）

```
全部待确认 · 缺金额 · 缺商家 · 疑似重复 · 可直接确认
```

“可直接确认” = 金额、商家、时间齐全且 `duplicate_status != suspected`。

### 禁止

- UI 层直接调用 Retrofit 或读 Room；必须经 ViewModel / Repository。
- UI 显示 `serverUrl` / `token` / `endpoint` / `ledgerId` 原始值。
- 为 Dashboard 改动账单状态机或新增后端枚举。

## `/web`：桌面账本流

### 顶部 LedgerSelector

- 渲染 owner 可见账本（`owner_console_service.list_console_ledgers`）。
- 默认账本 = owner 默认账本（不传 `ledger_id`）。
- 选中后所有 `pending` / `confirmed` / `stats` / `edit` / `confirm` /
  `reject` 都必须 carry `ledger_id` 并由 `_resolve_selected_ledger_id`
  在服务端 validate。
- 不可见 / 不存在的 `ledger_id` 必须 reject 成 `AppError`，不静默回退。

### 页面

```
/web              -> Dashboard（导航 + Selector + 卡片）
/web/pending      -> 桌面 Needs Review Queue
/web/confirmed    -> 桌面 Transaction Center（按月份过滤）
/web/stats        -> 桌面 Reports Cards
/web/expenses/{id}/edit    -> 快速编辑
/web/expenses/{id}/confirm -> POST 确认
/web/expenses/{id}/reject  -> POST 忽略
```

### Dashboard 卡片

```
当前账本 · 待确认 · 缺金额 · 疑似重复 · 本月已确认 · 本月笔数
```

### Reports Cards

```
本月总支出 · 分类排行 · 最近确认 · 大额支出 placeholder ·
预算 placeholder · 固定支出 placeholder
```

### 安全规则

- 仍 loopback only，公网 403；
- `ledger_id` 仅本机页面信任，不作公网 API 信任参数；
- 模板**不**渲染 `token_hash` / `upload_key` / pairing code / 绝对路径；
- Owner Console 仍 loopback。

## `/owner`：本机管理流

`/owner` 不是账本页，不显示复杂消费列表。

### Owner Dashboard 卡片

```
服务状态 · 设备状态 · UploadLink 状态 · 账本数量 · 最近备份 · 诊断入口 · 网页版账本入口
```

### 分区

```
设备管理 · 上传链接 · 账本管理 · 家庭成员 · 备份 · 诊断 · Windows 任务状态
```

### 账本管理页（`/owner/ledgers`）

每行字段顺序：

```
账本名 · 角色 · pending 数 · confirmed 数 · 最近更新时间 · 创建时间 · 操作：打开 /web?ledger_id=...
```

### 家庭成员管理

v0.4-beta1 后 `/owner` 已承载共享账本成员管理：

- 创建 / 撤销邀请，邀请明文只显示一次；
- 查看成员、角色和停用状态；
- 停用 active 非 owner 成员；
- 在 `member` / `viewer` 间调整 active 非 owner 成员角色。

仍然不做 owner 转让、co-owner、归档 / 删除，也不开放公网。

### 禁止

- 不显示 token / upload_key / pairing code 历史值；
- 不开放公网；
- 不把家庭成员加入共享账本解释为共享其个人账本。

## 视觉一致性收口（占位，详见 v0.4-alpha2 视觉系统文档）

- 卡片圆角、状态 badge 语义、金额字号层级、空状态、错误状态、离线/本地缓存
  在三端一致；
- Android 通过 `AppHeroCard` / `AppGlassCard` / `ReviewStatusChip` /
  `LedgerContextPill` / `DashboardSummaryCard` 复用；
- `/web` 与 `/owner` 共享 `:root` CSS 变量 + `.summary-grid` /
  `.summary-card` / `.status-chip` / `.ledger-pill` / `.transaction-row` /
  `.empty-state` / `.warning-card` / `.placeholder-card`。
