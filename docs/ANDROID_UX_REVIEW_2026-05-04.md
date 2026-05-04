# 小票夹 Android UX 审评记录

日期：2026-05-04

基于小米 15 Pro 真机截图与首版联调结果，本轮审评结论是：功能闭环已经通，下一阶段优先降低理解成本、减少重复控件、提升主题预览的真实感。

## 参考原则

本项目参考 Apple Human Interface Guidelines 与 Material Design 3，但不复制具体产品界面。

- Apple HIG 侧重清晰层级、内容优先、轻量材质与可读性。
- Material Design 3 侧重 color roles、组件状态、底部表单、chip 选择器和一致的交互反馈。
- 小票夹是私人生活账本，不做后台管理风，不把内部术语直接暴露给普通用户。

参考链接：

- <https://developer.apple.com/design/human-interface-guidelines/>
- <https://developer.android.com/develop/ui/compose/designsystems/material3>
- <https://developer.android.com/reference/kotlin/androidx/compose/material3/ModalBottomSheet>
- <https://developer.android.com/reference/kotlin/androidx/compose/material3/FilterChip>

## P0 结论

- 空状态需要告诉用户账单从哪里来，不能只写“没有数据”。
- 导出按钮必须提前判断是否可执行，无账单时禁用。
- 技术诊断默认只显示摘要，内部接口名称与 Token 细节折叠到详情。
- 清除缓存必须二次确认。
- 设置页面向用户时使用“连接测试”“检测连接”，不用“联调自检”。

## P1 本轮落实

- 账本页去掉月份输入框和月份标签的重复组合。
- 月份统一使用底部滑动选择面板。
- 分类筛选统一为横向 FilterChip，不再同时出现输入框和快捷标签。
- 港湾主题作为默认主题，色彩调整为海蓝加暖橙，不做单色深蓝。
- 主题卡片不再只显示色块，改为真实账单层级预览。
- UUID 与主题 JSON 只作为内部扩展能力，普通用户通过 UI 使用，不看原始 JSON。

## 后续 P1

- 统计页增加分类占比、最近 7 天趋势和高频商家排行。
- 设置页分类规则区域继续降密度，必要时拆成独立页面。
- 账本页增加更明确的月份选择动效和空状态插图。

## 不回退项

- 金额继续使用 `amount_cents` / `amountCents`。
- Android 不直接访问 uploads。
- 技术细节默认折叠。
- 普通 UI 不显示 UUID、数据库主键、接口路径、Token 名称或原始 JSON。
