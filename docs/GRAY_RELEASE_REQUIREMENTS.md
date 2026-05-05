# 小票夹灰度版总需求

日期：2026-05-05

本文是灰度版产品、架构、安全、Android UI/UX、发布、诊断和验收的总需求。后续实现必须以本文为入口，再进入各专项文档。

相关专项文档：

- `docs/GRAY_RELEASE_PRODUCT_SPEC.md`
- `docs/ANDROID_GRAY_UX_SPEC.md`
- `docs/MULTI_TENANT_SPEC.md`
- `docs/ANDROID_UPLOAD.md`
- `docs/RELEASE_PACKAGING.md`
- `docs/GRAY_ACCEPTANCE_CHECKLIST.md`
- `docs/LONG_TERM_ROADMAP.md`

## 1. 总目标

把“小票夹”从个人联调工程推进成可以给别人灰度试用、甚至可以给别人评估价值的私人记账 App。

灰度版本不仅仅是跑通功能，而是必须满足：

- 普通用户打开像生活账本 App，而不是开发面板。
- 灰度用户之间的账单、图片、统计、分类规则、重复检测相互隔离。
- 外网离开电脑范围后仍能稳定访问。
- iPhone 快捷指令和 Android App 均可上传截图。
- OCR 只填草稿，不自动入账。
- 有发布包、有诊断、有验收、有文档。
- 后续 OCR、大模型、Web 管理页和其他能力可插拔扩展。

## 2. 产品定位收口

普通用户应该看到：

- 待确认账单
- 账本
- 统计
- 我的账户 / 当前账本
- 连接状态
- 上传入口
- 编辑确认流程
- 最近上传
- 最近同步
- 外观
- 数据与安全

普通用户不应该默认看到：

- `127.0.0.1`
- `api.zen70.cn`
- `APP_TOKEN`
- 上传令牌 / `Upload-Token`
- `pending` / `confirmed` 接口名
- 数据库路径
- Cloudflare Tunnel 技术细节
- 日志
- 端口
- Windows 计划任务
- cloudflared 进程
- 服务器诊断明细
- 诊断脚本

技术信息只保留给：

- Windows 运维诊断脚本
- docs 运维文档
- 后续 Web 管理页面
- Android debug build 或隐藏高级入口

灰度用户的服务器不在他那里，所以普通 App 不显示服务器诊断，只显示自己的账本状态和同步状态。

## 3. 多租户隔离

第一版多租户不做账号密码、不做注册登录、不做复杂后台，先做配置式租户。

配置：

```env
TENANTS_JSON=[
  {"id":"owner","name":"我的小票夹","upload_token":"...","app_token":"..."},
  {"id":"tester_1","name":"灰度用户1","upload_token":"...","app_token":"..."}
]
```

兼容旧单用户配置：

```env
UPLOAD_TOKEN=...
APP_TOKEN=...
ADMIN_TOKEN=...
```

如果未配置 `TENANTS_JSON`，自动使用旧配置创建默认租户 `owner`，不能破坏现有个人使用。

后端需要新增：

- 租户配置
- 租户上下文
- `get_current_app_tenant()`
- `get_current_upload_tenant()`
- `get_current_admin_context()`

数据库要求：

- `Expense` 增加 `tenant_id`
- `CategoryRule` 增加 `tenant_id`
- `DuplicateIgnore` 增加 `tenant_id`
- 旧数据自动归到 `owner`
- 增加 `tenant_id + status + expense_time` 等必要索引

所有账单、图片、统计、分类规则、重复检测、CSV 导出都必须按 `tenant_id` 过滤。

必须测试：

- `tester_1` 看不到 `owner` 的 pending。
- `tester_1` 看不到 `owner` 的 confirmed。
- `tester_1` 无法下载 `owner` 的 image。
- `tester_1` 无法下载 `owner` 的 thumbnail。
- `tester_1` 统计不包含 `owner` 数据。
- `tester_1` 分类规则不影响 `owner`。
- `tester_1` 重复检测不跨租户。
- iOS `upload_token` 进入正确租户。
- Android `app_token` 上传到正确租户。

## 4. Android 体验重做

### 待确认页

要求：

- 默认紧凑模式。
- 顶部标题生活化，例如“待确认账单”。
- 增加主按钮“上传截图”。
- Android 使用系统 Photo Picker 选择图片。
- iOS 快捷指令作为补充上传方式，不占主屏幕。
- 账单卡片显示缩略图、金额草稿、商家草稿、分类、时间、状态。
- 缩略图小尺寸展示，点击进入详情页再看大图。
- OCR 未识别时显示“等待你确认金额”。
- OCR 低置信度时显示“请核对”。
- 空状态文案：“截图上传后，会出现在这里等你确认。”
- 不显示接口名、id、token、URL。

验收：

- 无 pending 时不是空白页。
- 有 pending 时一眼能看到要处理的账单。
- 上传成功后自动刷新列表。

### 编辑确认页

要求：

- 图片预览清晰。
- 金额作为第一输入项。
- 商家、分类、消费时间、备注依次展示。
- 分类用用户能理解的标签，不暴露内部字段。
- OCR 填出来的内容标记为“识别建议”。
- 用户修改后再确认入账。
- 确认按钮文案：“确认入账”。
- 拒绝 / 忽略入口弱化，避免误点。
- 重复疑似提示生活化，例如“这张可能已经记过了”。

验收：

- 未填金额不能确认。
- OCR 结果不会自动入账。
- 用户能明确知道确认后才进入账本。

### 账本页

要求：

- 月份选择显示为“2026年5月 ▼”。
- 点击月份后使用底部弹窗选择月份。
- 分类筛选用横向标签或二级筛选。
- 不要输入框和标签重复出现。
- 账单列表按日期分组，或至少按时间清晰排序。
- 每条账单展示金额、商家、分类、时间、备注摘要。
- 当前无数据时说明具体原因，例如“本月暂无餐饮账单”。
- 导出按钮在无数据时禁用，不要点了才失败。
- 不显示 `page`、`page_size`、`month`、`category` 这些接口概念。

验收：

- 用户不需要理解接口参数也能筛选账单。
- 无数据状态要清楚说明为什么没数据。

### 统计页

要求：

- 顶部总支出卡片。
- 显示账单数量。
- 显示分类占比。
- 显示最近 7 天支出。
- 显示最大一笔。
- 显示高频商家。
- 0 元分类隐藏或弱化。
- 文案生活化，例如“这个月主要花在餐饮上”。
- 不暴露接口名、字段名。

验收：

- 一屏能看懂本月花费概况。
- 没有数据时显示生活化空状态。

### 设置页

普通灰度用户默认只展示：

- 当前账本：租户名称 / 账本名
- 小票夹已连接
- 最近上传时间
- 最近同步时间
- 存储状态：正常
- 外观
- 数据与安全
- 清除本地数据
- 清除绑定 / 退出
- 关于

必须移出主展示：

- 服务器域名
- Cloudflare
- Tunnel
- 数据库大小
- pending 接口
- confirmed 接口
- token
- 本机服务
- 端口
- 后端日志
- 诊断脚本

要求：

- 清除本地数据必须二次确认。
- 清除绑定必须二次确认。
- 设置页文案要像 App 设置，不像 API 联调面板。
- 技术细节只允许放到 debug build、隐藏高级入口、Windows 诊断脚本、运维文档或后续 Web 管理页。

验收：

- 灰度用户看不到服务器域名和 token。
- 灰度用户看不到 Cloudflare、端口、日志、诊断脚本。
- 设置页只表达“我的账本是否正常可用”。

## 5. 外观和主题

目标：港湾主题重点打磨，形成默认审美。

要求：

- 港湾主题作为默认推荐。
- 主题卡片不只显示色块，要显示小型 App 预览。
- 支持背景选择。
- 后续支持用户自定义背景图。
- 背景必须有遮罩和对比度控制，不能影响文字可读性。
- 卡片、按钮、金额、分类标签要统一视觉语言。
- 各页面主题切换后都要保持可读。

验收：

- 主题切换后各页面文字清晰。
- 背景不抢文字。
- 港湾主题作为默认主题足够耐看。

## 6. Android 自带上传

Android 使用官方 Photo Picker，不申请全相册权限。

流程：

```text
用户点击“上传截图”
选择图片
App 转 multipart/form-data，字段名 file
请求头使用 Authorization: Bearer APP_TOKEN
后端创建待确认账单
上传成功后自动刷新待确认页面
```

新增接口：

```http
POST /api/app/upload-screenshot
Authorization: Bearer APP_TOKEN
Content-Type: multipart/form-data
file=图片
```

iOS 快捷指令继续使用旧接口：

```http
POST /api/upload-screenshot
Upload-Token: xxx
```

Android 不另外保存 `Upload-Token`。

## 7. 必须租户化的接口

以下接口必须按租户过滤：

```text
GET /api/expenses/pending
GET /api/expenses/confirmed
GET /api/expenses/{id}
PATCH /api/expenses/{id}
POST /api/expenses/{id}/confirm
POST /api/expenses/{id}/reject
GET /api/expenses/{id}/image
GET /api/expenses/{id}/thumbnail
POST /api/expenses/{id}/ocr/retry
POST /api/expenses/{id}/recognize-text
POST /api/expenses/{id}/mark-not-duplicate
GET /api/stats/monthly
GET /api/stats/lifestyle
GET /api/rules/categories
POST /api/rules/categories
PATCH /api/rules/categories/{id}
DELETE /api/rules/categories/{id}
GET /api/duplicates
GET /api/settings/server
GET /api/expenses/export.csv
POST /api/app/upload-screenshot
POST /api/upload-screenshot
```

## 8. OCR 规则路线

暂时不上大模型，先继续规则 OCR。

目标：

```text
截图 -> OCR -> 自动填草稿 -> 用户检查 -> 确认入账
```

补样本和规则：

- 建行
- 美团
- 京东
- 微信支付
- 支付宝
- 滴滴
- 饿了么
- 淘宝
- OpenAI
- Steam

抽取字段：

- 金额
- 商家
- 实际消费时间 `expense_time`
- 分类建议
- OCR 原文 `raw_text`
- 置信度 `confidence`

原则：

- OCR 只填草稿，不自动入账。
- 低置信度时提示核对。
- 不允许自动确认。

## 9. 发布包

补 release 版本：

- release 签名配置。
- keystore 路径从环境变量读取。
- 密钥密码不进 Git。
- `scripts/build_release_apk.ps1`。
- 输出 APK 路径。
- 版本号说明。
- 安装说明。
- debug / release 区别说明。

环境变量示例：

```powershell
$env:TICKETBOX_KEYSTORE_PATH="E:\secrets\ticketbox-release.jks"
$env:TICKETBOX_KEY_ALIAS="ticketbox"
$env:TICKETBOX_KEYSTORE_PASSWORD="..."
$env:TICKETBOX_KEY_PASSWORD="..."
```

输出：

```text
android/app/build/outputs/apk/release/app-release.apk
```

Release 要求：

- 不打印网络调试日志。
- 不暴露令牌。
- 不显示开发诊断入口。

## 10. 分层诊断

普通 App 只显示：

- 小票夹已连接
- 最近同步时间
- 最近上传时间
- 存储状态：正常
- 当前账本名
- 清除本地数据
- 清除绑定 / 退出

Windows 服务拥有者诊断继续增强：

```text
scripts/diagnose_ticketbox.ps1
```

摘要示例：

```text
小票夹服务诊断
本地服务：正常
外网访问：正常
Cloudflare Tunnel：在线
最近上传：2026-05-05 17:19
待确认：0 笔
已入账：3 笔
数据库大小：xx MB
图片占用：xx MB
租户数量：2
默认租户：我的小票夹
```

高级模式才显示：

- 端口
- URL
- HTTP 状态码
- cloudflared 进程
- 计划任务名称
- 日志尾部

诊断是运维工具，不进普通 App 主体验。

## 11. 成品验收

必须跑通：

- iPhone 快捷指令上传真实账单。
- 后端 pending 增加。
- Android 待确认出现。
- Android 编辑金额、商家、分类、备注。
- Android 确认入账。
- 账本页出现。
- 统计页金额变化。
- Android 选择图片上传。
- Android 上传后 pending 出现。
- 蜂窝网络访问 `api.zen70.cn`。
- 离开电脑局域网后仍能访问。
- 多租户 token 互相看不到数据。
- 图片接口不能跨租户读取。
- CSV 不能跨租户导出。
- 分类规则不能跨租户影响。

## 12. 文档要求

需要持续更新：

- `docs/ARCHITECTURE.md`
- `docs/API.md`
- `docs/SECURITY.md`
- `docs/ANDROID_RULES.md`
- `docs/BACKEND_RULES.md`
- `docs/REAL_DEVICE_RUNBOOK.md`
- `docs/WINDOWS_SERVICE_RUNBOOK.md`
- `docs/IOS_SHORTCUT.md`
- `docs/CI.md`
- `docs/PROJECT_STRUCTURE.md`

新增并维护：

- 多租户决策文档
- 发布包文档
- Android 上传说明
- 阶段性验收清单
- Android 灰度 UX 规格
- 灰度版产品规格

## 13. 执行顺序

1. 多租户基础和兼容旧 token。
2. 租户化账单、上传、统计、规则、设置、重复检测、CSV。
3. Android 上传接口和 Photo Picker。
4. UI 去开发味和设置页收口。
5. Release 脚本。
6. OCR 样本规则。
7. 文档。
8. 本地验证。
9. 真机验证。
10. GitHub 发布。
11. CI 绿灯。

## 14. 灰度前底线

- 账单不串租户。
- 图片不串租户。
- 令牌不暴露。
- 普通 App 没有开发面板。
- Android / iPhone 均可上传。
- OCR 不自动入账。
- Release APK 可安装。
- Windows 诊断可用于服务拥有者排障。
- 文档能让后续维护继续推进。

## 15. 外部参考使用规则

允许调用浏览器查看外部成熟产品和官方规范，但只能用于校正体验方向。

官方规范优先级高于社区帖子和产品截图：

- Android Photo Picker 用于 Android 上传入口。
- Android App Signing 用于 release 包。
- Material Design 3 用于导航、卡片、列表、主题、状态反馈。
- Apple Human Interface Guidelines 用于普通用户可理解性、设置页层级和隐藏复杂性。

成熟产品只参考模式：

- 账本首页如何组织主操作。
- 统计页如何讲生活化总结。
- 设置页如何隐藏技术复杂度。
- 主题预览如何帮助用户理解外观。

禁止：

- 照搬外部 UI。
- 使用外部产品素材。
- 使用外部产品商标或专有文案。
- 为了“像某个产品”破坏小票夹的截图确认闭环。
