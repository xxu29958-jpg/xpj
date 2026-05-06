# 小票夹设计目标

本文件把两个设计包转成可执行的 UI 验收标准。设计包是验收基准，不是灵感参考。
如果本机图片不可用，本文的文字描述仍然应足够指导实现。

## 1. 页面映射

| App 页面 | 设计基准 | 目标 |
| --- | --- | --- |
| PendingScreen | `01_pending_redesign.png` | 待确认标杆页，最接近设计稿。 |
| ExpenseEditScreen | `02_edit_confirm_redesign.png` | 清晰核对截图和表单，确认入账是主操作。 |
| LedgerScreen | `03_ledger_redesign.png` | 查账效率优先，视觉统一但不强行宣传图化。 |
| StatsScreen | `04_stats_redesign.png` | 生活化统计，有总览、分类、商家、趋势质感。 |
| SettingsScreen | `05_settings_redesign.png` | 保持二级信息架构，入口卡统一、克制、清楚。 |
| Brand mood | `00_promo_poster.png` | 温润、安全、低饱和、半自动生活账本。 |

## 2. 主题映射

- 松雾：暖白、雾绿、低饱和、松林晨雾感。背景有雾面和轻青绿，Hero 使用深松绿，卡片为暖白玻璃。
- 柚光：暖白、柚黄、晨光、治愈感。背景有柔和金色光晕，按钮和 chip 使用低饱和柚黄。
- 港湾：浅蓝白、海蓝、海雾、可靠感。背景有海蓝雾感和局部暖沙色，主色偏稳重海蓝。
- 莓果：奶白、莓红、柔粉、温暖感。背景柔粉但不甜腻，阴影和状态强调偏莓红。
- 夜幕：深色、深青绿、月光、私密感。背景为深色松林夜雾，卡片更实体，文本高对比。

每套主题必须影响页面背景、Hero 卡、主按钮、chip、空状态插画底色、卡片 tint、阴影 tint、底部导航选中态和图表辅助色。错误、成功、警告语义色不能随背景随意变化。

## 3. UX 映射

核心流程来自 `UX交互_核心流程.png`：

```text
绑定服务器 -> 生物识别 -> 待确认 -> 编辑确认 -> 账本统计
```

关键状态来自 `UX交互_关键状态与微交互.png`：

- loading：不遮挡页面主标题，按钮防重复点击。
- success：反馈轻，不打断用户。
- error：说明原因和下一步。
- empty：告诉用户下一步能做什么。
- duplicate：只提示，不自动删除或拒绝。
- OCR retry：只更新草稿，不自动入账。
- CSV export：无数据时禁用或提示原因，导出后给轻反馈。
- network error：离线状态不要像致命错误，账本可提示本地缓存。

## 4. 视觉关键词

小票夹视觉关键词：

- 温润
- 安全
- 半自动
- 低饱和
- 磨砂
- 柔和阴影
- 玻璃卡片
- 背景有氛围但不抢内容

原则：

```text
背景负责情绪。
卡片负责信息。
按钮负责效率。
越需要阅读和输入，界面越克制。
越偏展示和概览，氛围可以更强。
```

## 5. 80% 视觉还原定义

80% visual parity means:

- screen structure matches the target
- background atmosphere is recognizable
- Hero card has gradient/glow/shadow and clear hierarchy
- cards use unified radius, tint, border and shadow
- primary CTA is obvious
- empty state is polished
- bottom nav is unified
- Ledger/Edit remain readable
- the screen no longer looks like default Material UI
- real device screenshot passes human review

## 6. 页面验收原则

- PendingScreen 是标杆页。未通过人工 review 前，不允许批量改 Ledger / Stats / Settings / Edit。
- LedgerScreen 保持查账效率；金额、商家、时间、分类必须清楚。
- StatsScreen 有生活化统计质感，无数据时不显示假金额。
- SettingsScreen 保持二级信息架构，主展示不变成技术面板。
- ExpenseEditScreen 是任务页，表单和确认入账优先级高于沉浸感。
- 五套主题不是简单换色，而是完整视觉气质。

## 7. 产品边界

视觉还原不得破坏以下业务边界：

- 上传只创建 pending。
- OCR 只填草稿。
- 重复检测只提示。
- 用户确认才 confirmed。
- confirmed 才进入账本和统计。
