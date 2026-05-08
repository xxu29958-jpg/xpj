# 小票夹灰度版产品规格

日期：2026-05-05

## 1. 目标

把“小票夹”从个人联调工程推进成可以给别人灰度试用的私人生活记账 App。

灰度版不是后台控制台，也不是接口联调面板。普通用户打开后应该看到一个能理解、能上传、能确认、能看账本和统计的生活账本 App。

灰度版必须满足：

- 普通用户打开像生活账本 App。
- 灰度用户之间的账单、图片、统计、分类规则、重复检测互相隔离。
- 离开电脑局域网后仍能通过公网域名访问。
- iPhone 快捷指令和 Android App 都能上传截图。
- OCR 只填草稿，不自动入账。
- 有发布包、有运维诊断、有验收清单、有文档。
- 后续 OCR、大模型、Web 管理页和图片处理能力可以插拔扩展。

## 2. 用户视角

普通用户默认应该看到：

- 待确认账单
- 上传截图入口
- 账本
- 统计
- 当前账本名
- 小票夹已连接
- 最近上传
- 最近同步
- 外观
- 数据与安全
- 编辑和确认入账流程

普通用户默认不应该看到：

- `127.0.0.1`
- `api.zen70.cn`
- `APP_TOKEN`
- `Upload-Token`
- `pending` / `confirmed` 接口名
- 数据库路径
- Cloudflare Tunnel
- 端口
- 后端日志
- cloudflared 进程
- scheduled task
- 服务器诊断明细
- 诊断脚本

技术信息只允许出现在：

- Windows 运维诊断脚本
- 运维文档
- 后续 Web 管理页
- Android debug build 的隐藏高级入口

灰度用户的服务器不在他那里，所以普通 App 主界面和设置页不能显示服务器诊断。

## 3. 产品边界

小票夹灰度版仍然是“私人半自动账本”。

做：

- 截图上传。
- OCR 草稿建议。
- 用户手动核对。
- 用户确认入账。
- 本地缓存已确认账单。
- 按月、分类、商家、最近 7 天做轻量统计。
- 多租户隔离灰度测试。

不做：

- 自动入账。
- 银行卡接口。
- 微信/支付宝自动监听。
- 账号密码注册。
- 多人共享账本协作。
- 普通用户可见的服务器管理。
- 远程控制 Windows 主机。

## 4. 术语统一

面向用户：

```text
账本
待确认
已入账
截图
识别建议
可能重复
忽略这张
确认入账
小票夹服务
```

面向代码和后端文档：

```text
tenant
pending
confirmed
rejected
upload_token
app_token
tenant_id
```

禁止在普通 UI 中出现：

```text
租户
tenant
API
endpoint
token
Cloudflare
Tunnel
pending interface
confirmed pagination
```

## 5. 灰度隔离

第一版多租户不做账号密码、不做注册、不做复杂后台，采用配置式租户。

配置示例：

```env
TENANTS_JSON=[
  {"id":"owner","name":"我的小票夹","upload_token":"...","app_token":"..."},
  {"id":"tester_1","name":"灰度用户1","upload_token":"...","app_token":"..."}
]
```

兼容旧配置：

```env
UPLOAD_TOKEN=...
APP_TOKEN=...
ADMIN_TOKEN=...
```

如果未配置 `TENANTS_JSON`，后端自动使用旧配置生成默认租户 `owner`，旧数据迁移到 `owner`。

当前实现中 `TENANTS_JSON` 只配置 `upload_token` 和 `app_token`。`ADMIN_TOKEN` 是独立维护令牌，返回默认租户的 admin 上下文，用于窄维护接口。

必须按 `tenant_id` 隔离：

- 账单
- 图片
- 缩略图
- 统计
- CSV 导出
- 分类规则
- 重复检测
- 服务器设置摘要

## 6. 上传入口

iPhone：

```http
POST /api/upload-screenshot
Upload-Token: <tenant upload token>
```

Android：

```http
POST /api/app/upload-screenshot
Authorization: Bearer <tenant app token>
Content-Type: multipart/form-data
file=<image>
```

Android 不保存 `Upload-Token`。用户绑定一次 App Token 后，App 自己具备上传权限。

新上传图片保存到 `uploads/{tenant_id}/YYYY/MM/`。历史 `uploads/YYYY/MM/...` 路径会在文件存在时迁移到租户目录；文件已丢失时保留记录，访问返回 `image_not_found`。

## 7. UI 总原则

灰度版 UI 的目标是清楚、耐看、生活化。

设计约束：

- 港湾主题作为默认推荐。
- 默认信息密度中等偏低，避免后台报表感。
- 技术信息折叠或移出普通用户体验。
- 以“账本状态”和“用户下一步动作”为主，不以接口状态为主。
- 空状态必须有说明和主操作。
- 危险操作必须二次确认。
- 图片缩略图默认小尺寸，详情页再展示大图。
- OCR 文案用“识别建议”，不用技术词压用户。

## 8. 参考原则

外部参考用于提炼模式，不照搬 UI。

- Android Photo Picker：用于 Android 上传截图，避免申请全相册权限。
- Android App Signing：用于 release 签名和发布包。
- Material Design 3：用于底部导航、卡片、设置列表、主题色和状态反馈。
- Apple Human Interface Guidelines：用于层级、设置页、普通用户可理解性和隐藏复杂性。
- 成熟记账/消费类 App：参考“账本、分类、统计、账户状态”如何面向普通用户表达。

参考外部产品时必须遵守：

- 不复制商标、图标、插画、截图、素材或专有文案。
- 不把其他产品的信息架构生搬硬套到小票夹。
- 只提炼通用体验模式，例如清晰主操作、生活化空状态、折叠高级信息、可读的统计摘要。
- 小票夹以“截图草稿 -> 人工确认 -> 私人账本”为核心，不做预算 SaaS 或多人协作产品。

## 9. 实施顺序

1. 多租户基础和旧 token 兼容。
2. 租户化上传、账单、统计、规则、设置、重复检测、CSV。
3. Android 上传截图入口。
4. Android UI 去开发味。
5. Release 签名脚本。
6. OCR 样本和规则。
7. 文档更新。
8. 本地测试。
9. 真机测试。
10. GitHub 发布和 CI。

## 10. 灰度前底线

- 账单不串租户。
- 图片不串租户。
- CSV 不串租户。
- 分类规则不串租户。
- 重复检测不跨租户。
- token 不暴露。
- 普通 App 没有开发面板。
- Android 和 iPhone 均可上传。
- OCR 不自动入账。
- Release APK 可安装。
- Windows 诊断能给服务拥有者排障。
