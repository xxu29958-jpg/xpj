# 小票夹长期项目规划

日期：2026-05-05

本文只描述长期方向，不改变灰度版底线。当前灰度版仍以“截图上传 -> 识别草稿 -> 用户确认 -> 入账”为核心，不做自动入账。

## 1. 阶段划分

### G0 灰度稳定版

目标：能给少量真实用户试用，不像开发面板。

范围：

- 多租户配置式隔离。
- iPhone 快捷指令上传。
- Android Photo Picker 上传。
- OCR 草稿建议。
- 待确认、编辑、确认、账本、统计闭环。
- gray/internal 两版分离。
- Windows 诊断和 release 构建脚本。
- 文档和验收清单可复跑。

退出标准：

- 账单、图片、CSV、统计、分类规则、重复检测不串租户。
- 普通灰度 App 不显示服务器域名、Token、Cloudflare、端口、日志或诊断入口。
- Android/iPhone 均可上传截图。
- OCR 不自动入账。
- release APK 可构建和安装。
- Windows 主机在线时，蜂窝网络可访问公网域名。

### G1 试用反馈版

目标：让 3 到 10 个灰度用户稳定试用一周，收集真实账单类型。

范围：

- 灰度租户配置模板和发放流程。
- 用户反馈入口。
- 上传失败、识别失败、低置信度的生活化提示。
- 更细的空状态和新用户引导。
- 账单详情里的“识别建议”解释。
- 更多分类图标和自定义分类颜色。

不做：

- 账号注册系统。
- 自动扣款或支付接口。
- 复杂团队协作。

### G2 OCR 规则增强版

目标：常见账单截图能自动填好金额、商家、消费时间和分类建议。

优先样本：

- 建行。
- 微信支付。
- 支付宝。
- 美团。
- 京东。
- 饿了么。
- 滴滴。
- 淘宝。
- OpenAI。
- Steam。

原则：

- OCR 结果只填草稿。
- 低置信度必须提示核对。
- 任何规则不得自动确认入账。
- 规则引擎必须可替换，不写死在 route 层。

扩展点：

```text
services/
  ocr_service.py
  receipt_parse_service.py
  classify_service.py
  duplicate_service.py
```

### G3 产品化体验版

目标：更像成熟私人账本，而不是截图确认工具。

范围：

- 更精致的账本月视图。
- 分类消费趋势。
- 预算和月度提醒。
- 商家排行和生活化总结。
- 主题背景自定义。
- 更顺滑的图片预览和编辑流程。
- 账单搜索、标签和轻量复盘。

底线：

- 不牺牲数据正确性和租户隔离。
- 不引入浮点金额。
- 不暴露技术诊断给普通用户。

### G4 运维和发布版

目标：服务拥有者能长期稳定跑在 Windows 主机上。

范围：

- Windows 计划任务稳定化。
- Tunnel 在线检查。
- 后端日志轮转。
- 数据库备份和恢复。
- 上传目录占用预警。
- 灰度租户配置检查。
- release APK 版本、签名和发布记录。

后续可选：

- GitHub Release 自动附带 APK 和校验摘要。
- Web 管理页只给服务拥有者使用。
- Cloudflare Access 保护 Web 管理页。

### G5 插拔智能版

目标：在规则 OCR 稳定后，接入更强的本地或云端智能能力。

可插拔能力：

- OCR provider。
- 本地大模型解析 provider。
- 分类 provider。
- 重复检测 provider。
- 图片压缩和缩略图 provider。

约束：

- provider 通过配置切换。
- provider 失败必须 fallback 到规则或空实现。
- 不把模型调用写死进 route。
- 不让模型自动确认账单。
- 不把用户截图发到第三方服务，除非用户明确配置并理解风险。

## 2. 技术债控制

每个阶段都必须继续遵守：

- 金额用 `amount_cents`。
- 数据库时间用 UTC。
- 普通 API 错误统一 `{error, message}`。
- uploads 不公开。
- 图片只通过受保护接口读取。
- Android UI 不直接调 Retrofit 或 Room。
- Room confirmed 用 serverId upsert。
- PowerShell 脚本用 UTF-8 with BOM。
- 关键决策写入 `docs/DECISIONS/`。

## 3. 版本分支建议

```text
main                         稳定主线
codex/gray-release-tenant-ux 当前灰度版推进分支
codex/ocr-rules              OCR 规则增强
codex/product-polish         产品体验打磨
codex/windows-ops            Windows 运维增强
```

不要在一个提交里同时混合大规模后端、多租户、Android UI、OCR 和文档重构。

## 4. 验收节奏

每次合入前必须跑：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\verify_project.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check_text_encoding.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\diagnose_ticketbox.ps1 -Strict
```

灰度发布前额外跑：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\accept_gray_release.ps1 -UseTemporaryKeystore
```

真机人工验收仍不可省略：

- iPhone 真实账单上传。
- Android 解锁后上传截图。
- 编辑确认入账。
- 账本和统计变化。
- 蜂窝网络访问公网域名。
