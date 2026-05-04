# Android 开发规则

Android 使用轻量 MVVM：

```text
Screen -> ViewModel -> Repository -> ApiService / Dao / TokenStore
```

## Screen

职责：

- 展示 UI。
- 收集用户输入。
- 触发 ViewModel 事件。

禁止：

- 直接调用 Retrofit。
- 直接调用 Room。
- 直接读写 SharedPreferences。
- 直接保存 Token。
- 写复杂业务逻辑。

## ViewModel

职责：

- 管理页面状态。
- 调用 Repository。
- 处理加载中、成功、失败。
- 暴露 UI State。

禁止：

- 创建 Retrofit。
- 创建 Room Database。
- 持有 Activity。
- 直接操作 Keystore 加密细节。

## Repository

职责：

- 协调远程 API 和本地 Room。
- 解析后端统一错误结构。
- 同步 confirmed 账单。
- 服务器失败时 fallback 到本地缓存。

禁止：

- 写 Compose 状态。
- 写 UI 控件逻辑。
- 返回 DTO 给 UI。

## DAO

职责：

- Room 查询。
- Room upsert。
- Room 删除。

禁止：

- 返回 DTO。
- 调用网络。
- 处理 Token。

## 数据模型

三类模型分开：

```text
DTO      服务端接口模型
Entity   Room 本地模型
Domain   App 内业务模型
```

转换集中在：

```text
ExpenseMappers.kt
```

UI 不能直接使用 DTO 或 Entity。

## 金额与时间

- Room 使用 `amountCents: Long?`。
- UI 显示时才转换为元。
- Android 不生成 `confirmedAt`。
- Android 显示时间时把后端 UTC ISO 字符串转本地时间。

## Room 同步

`serverId` 必须唯一。

同步 confirmed 账单时：

```text
serverId 已存在 -> 更新本地记录
serverId 不存在 -> 插入本地记录
```

不允许重复插入。

实现要求：

- DAO 必须提供按 `serverId` 查询旧记录的能力。
- 更新时保留本地自增主键 `id`。
- 不依赖“看起来像 upsert”的主键冲突行为来替代 `serverId` 唯一同步。

## Token 与日志

- APP_TOKEN 不写死。
- APP_TOKEN 不打印日志。
- APP_TOKEN 不明文写 SharedPreferences。
- 使用 Android Keystore 保存。
- OkHttp 日志最多 BASIC，不打印 Header 和 Body。

## 受保护图片

- Android 不直接访问 `uploads` 路径。
- 缩略图和原图必须通过 Repository 调用受保护接口获取。
- UI 层只负责解码和展示二进制图片，不拼接带 Token 的图片 URL。
- HEIC 原图如果无法解码，显示“截图已保存，当前格式暂不预览”。
