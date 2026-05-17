# Android 开发规则

灰度版 Android 以当前 `docs/ARCHITECTURE.md`、`docs/ANDROID_STATE_FLOW.md`、`docs/ANDROID_UPLOAD.md` 和 `docs/ANDROID_APPEARANCE_BACKGROUND.md` 为准。普通用户主体验不得显示服务器域名、token、接口名、Cloudflare、端口、后端日志或诊断脚本。技术诊断只允许在 debug build 隐藏入口、Windows 运维脚本、运维文档或后续 Web 管理页中出现。

## 分层

Android 使用轻量 MVVM：`Screen -> ViewModel -> Repository -> ApiService / Dao / TokenStore`。各层职责和禁止项详见 `docs/ENGINEERING_RULES.md` §12（Android 分层）。数据模型（DTO / Entity / Domain）和转换规则见 §13。Token 安全规则见 §15。

Repository 层额外职责：解析后端统一错误结构。

## 金额与时间

- Room 使用 `amountCents: Long?`。
- UI 显示时才转换为元。
- Android 不生成 `confirmedAt`。
- Android 显示时间时把后端 UTC ISO 字符串转本地时间。

## Room 同步

`publicId` 必须唯一；Room 的 `serverId` 唯一性必须限定在当前账本，即 `(ledgerId, serverId)` 唯一。

Room schema 必须导出到：

```text
android/app/schemas/
```

后续修改 Room Entity 或数据库版本时，必须提交 schema 变化，并补迁移策略或明确重建策略。

同步 confirmed 账单时：

```text
当前 ledgerId 下 serverId 已存在 -> 更新本地记录
当前 ledgerId 下 serverId 不存在 -> 插入本地记录
```

不允许重复插入。

实现要求：

- DAO 必须提供按 `(ledgerId, serverId)` 查询旧记录的能力。
- 批量同步 confirmed 时必须在当前 `ledgerId` 内批量查询已有 `serverId`，再批量 insert/update；不允许回到逐条 SELECT + 写入，也不允许跨账本复用本地主键。
- `publicId` 来自后端 `public_id`，不得由 Android 为新同步账单伪造。
- 老版本本地缓存迁移到 `publicId` 时，可以用 `server-<serverId>` 作为兼容占位；后续服务端同步会写入真实 UUID。
- 如果服务端响应缺少 `public_id`，App 必须显示"服务器版本过旧，请重启 Windows 后端后再试。"，不能把 JSON 字段名或解析异常直接显示给用户。
- 更新时保留本地自增主键 `id`。
- 不依赖"看起来像 upsert"的主键冲突行为来替代 `(ledgerId, serverId)` 唯一同步。
- 本地账本排序过滤字段必须保留索引迁移，包括 `status + expenseTime`、`status + confirmedAt`、`status + createdAt`。

## 错误文案与日志

- App 主流程只显示生活化短文案，例如"连接不上服务器，请稍后再试"。
- 不在绑定页、弹窗、Toast、Snackbar 中直接暴露 DNS、TLS、Tunnel、localhost、Token 校验、接口名等工程细节。
- 网络异常的技术原因写入 Android Logcat，统一使用 `TicketboxNetwork` tag。
- 设置页"连接检测"可以展示简化后的状态，不把内部实现细节作为默认内容。

## 依赖管理

- Android 依赖版本集中在 `android/gradle/libs.versions.toml`。
- 根工程和 App 模块通过 `libs.plugins.*`、`libs.*` 引用插件与库。
- 模块 `build.gradle.kts` 不散写第三方库版本号。
- 新增依赖前确认来源可靠、活跃维护，并避免 alpha/beta 弱依赖进入主线。
- 依赖升级前先运行 `scripts\check_dependency_versions.ps1`，再查官方 release notes。
- 依赖调整后必须运行单元测试、debug 构建和 lint。

## 自定义背景与沉浸模式

- 自定义背景是 Android 本地 UI 个性化能力，不改后端接口。
- 背景选择必须使用 Android Photo Picker，优先不申请 `READ_MEDIA_IMAGES`。
- Picker 返回的 `Uri` 不长期保存；选中后复制到 `context.filesDir/backgrounds/custom_background.jpg`。
- 背景路径只进入本机 DataStore，不进入 Room，不上传后端，不写入导出文件。
- 背景渲染只能放在统一 `ImmersiveBackgroundScaffold` / `TicketboxBackgroundLayer`，不允许散落到每个 Screen。
- 主题语义色不跟随背景图片随机变化，金额、表单、主按钮、错误/成功/警告反馈必须稳定高对比。
- 编辑、设置、绑定、生物识别等录入或安全页面必须使用更强遮罩和更实体的卡片。
- 相册大图解码必须做尺寸采样，避免用原图尺寸直接进入 Compose 背景层。

## 受保护图片

- Android 不直接访问 `uploads` 路径。
- 缩略图和原图必须通过 Repository 调用受保护接口获取。
- UI 层只负责解码和展示二进制图片，不拼接带 Token 的图片 URL。
- HEIC 原图如果无法解码，显示"截图已保存，当前格式暂不预览"。

## 真机联调

- Windows 真机安装使用 `android\install_debug_apk.bat`。
- 脚本只允许安装已构建的 debug APK，或先构建再安装。
- 脚本不读取、不输出、不保存旧 token；DebugBind 只接受显式传入的 session token。
- 多设备连接时必须显式指定 `-Serial`。
- 灰度用户首次绑定后只查看账本连接状态；内部联调版可在设置页运行"运行诊断"。
