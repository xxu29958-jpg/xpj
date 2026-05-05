# Android 设置与背景系统实现状态

日期：2026-05-06

分支：`codex/gray-release-tenant-ux`

本文件记录「设置二级菜单 + 外观与主题 + 背景图库 + 自定义背景 + 裁剪 + 预览 + 沉浸强度」阶段的实际落地状态。产品规格见 `docs/ANDROID_APPEARANCE_BACKGROUND.md`，Android 灰度 UX 总规则见 `docs/ANDROID_GRAY_UX_SPEC.md`。

## 1. 已完成范围

### 文档

- 已新增状态流入口：`docs/ANDROID_STATE_FLOW.md`
- 已新增完整状态流规格：`docs/ANDROID_STATE_FLOWS.md`
- 已新增外观、背景、预览、裁剪、沉浸模式规格：`docs/ANDROID_APPEARANCE_BACKGROUND.md`
- 已更新灰度 UX、Android 规则、灰度需求和项目结构索引。

### 设置页信息架构

设置页已经拆成一级入口和二级页面：

```text
设置
├─ 服务器与联调
├─ 外观与主题
├─ 分类规则
├─ 数据与导出
├─ 安全与隐私
└─ 关于
```

当前二级页面文件：

```text
android/app/src/main/java/com/ticketbox/ui/screens/settings/
  SettingsRoute.kt
  SettingsRootScreen.kt
  ServerSettingsScreen.kt
  AppearanceScreen.kt
  BackgroundGalleryScreen.kt
  BackgroundPreviewScreen.kt
  BackgroundCropScreen.kt
  CategoryRulesScreen.kt
  DataExportScreen.kt
  SecurityPrivacyScreen.kt
  AboutScreen.kt
  SettingsComponents.kt
```

`SettingsScreen.kt` 只负责 route 状态、二级页面分发、返回和 Photo Picker 入口，不再承载全部设置 UI。

### 外观与主题

- 港湾主题保留为默认推荐。
- 主题卡片已改为小型 App 预览，不再只是色块。
- 外观与主题已独立为二级页面。
- 普通 gray 版不默认展示服务器域名、token、接口名、Cloudflare、端口、日志或诊断脚本。

### 背景系统

已新增独立模块：

```text
android/app/src/main/java/com/ticketbox/ui/appearance/
  BackgroundCatalog.kt
  BackgroundPreviewModels.kt
  AppearanceDefaults.kt
  background/
    BackgroundImageStore.kt
    ImmersiveBackground.kt
```

已实现：

- `BackgroundSource.ThemeDefault`
- `BackgroundSource.BuiltIn`
- `BackgroundSource.CustomImage`
- `ImmersionMode.Atmosphere`
- `ImmersionMode.Balanced`
- `ImmersionMode.Focus`
- 背景图库页
- 背景分类
- 背景预览页
- 自定义背景裁剪页
- 主题默认背景恢复
- 点击“应用背景”才保存
- 取消预览不污染当前设置
- 背景层统一接入 App Shell

### 内置背景包

当前内置 8 个背景：

| 名称 | 分类 | 推荐主题 |
| --- | --- | --- |
| 松雾 | 自然 | 松雾 |
| 港湾 | 自然 | 港湾 |
| 柚光 | 情绪 | 柚光 |
| 莓果 | 情绪 | 莓果 |
| 夜幕 | 自然 | 夜幕 |
| 纸感 | 极简 | 柚光 |
| 暖雾 | 极简 | 港湾 |
| 云层 | 插画 | 港湾 |

第一阶段使用渐变占位图，重点是信息架构、预览、保存和回退流程稳定。

### 自定义背景

已实现流程：

```text
设置
  -> 外观与主题
  -> 从相册选择
  -> Photo Picker
  -> 复制到 App 私有目录
  -> 裁剪页
  -> 预览页
  -> 应用背景
```

工程边界：

- 不保存外部图库 `Uri`。
- 不请求全相册权限。
- 不上传背景图片。
- 背景图片只保存到 App 私有目录。
- 背景路径只进入本机 DataStore。
- 不进入 Room。
- 不进入后端。
- 不进入 CSV 导出。

### 沉浸背景层

已实现统一背景层：

```text
ImmersiveBackgroundScaffold
TicketboxBackgroundLayer
SurfaceRole
resolveBackgroundAlpha
resolveScrimAlpha
resolveCardContainerAlpha
```

页面角色：

```text
Pending
Ledger
Stats
Edit
Settings
Auth
```

规则：

- 待确认和统计背景更明显。
- 账本中等沉浸，优先扫读。
- 编辑、设置、绑定和解锁更克制，优先表单和安全操作。
- 金额、正文、主按钮、错误、成功、警告色不跟随背景图片乱变。

## 2. 已补测试

已覆盖：

- `BackgroundSettings` 默认值。
- 背景来源保存和读取。
- DataStore 保存和读取 `immersionMode`。
- 清除背景后回到 `ThemeDefault`。
- 自定义背景路径不存在时 fallback。
- 内置背景 id 不重复。
- 内置背景分类正确。
- `resolveBackgroundAlpha` 在编辑和设置页低于待确认和统计页。
- `resolveCardContainerAlpha` 在编辑和设置页高于待确认和统计页。
- `BackgroundPreviewState` 修改预览沉浸强度不会立即污染已应用设置。

## 3. 已跑验证

本阶段已通过：

```powershell
cd android
.\gradlew.bat --no-daemon :app:compileGrayDebugKotlin
.\gradlew.bat --no-daemon :app:testGrayDebugUnitTest
.\gradlew.bat --no-daemon :app:lintGrayDebug
.\gradlew.bat --no-daemon :app:assembleGrayDebug
.\gradlew.bat --no-daemon :app:installGrayDebug
```

已用 ADB 做过基础真机检查：

- App 可启动。
- 待确认页可打开。
- 设置页显示一级入口。
- 外观与主题页可打开。
- 背景图库可打开。
- 背景预览页可打开。

本地验证截图：

```text
artifacts/ticketbox-appearance.png
artifacts/background_preview.png
```

## 4. 对应提交

```text
f32cc2c docs: add android state and appearance specs
2b4d4fd feat(android): add settings routes and background system
a9e9562 refactor(settings): split secondary screens by route
```

## 5. 明确未完成但已预留

以下属于后续增强，不计入本阶段完成口径：

- 最近使用背景完整 UI。
- 背景最多保留 5 个的完整数据结构和清理策略。
- 背景主色提取。
- 背景推荐机制。
- 真正可拖拽、可缩放的高级裁剪。
- 轻微视差完整动效。
- 动效性能专项测试。
- 内置背景真实图片素材替换。

当前裁剪页为安全、低风险的第一版流程：支持选择裁剪位置和竖屏安全区提示，保证“选择 -> 裁剪 -> 预览 -> 应用”的主链路先稳定。

## 6. 后续建议顺序

下一阶段建议按以下顺序继续：

1. 真机完整走一遍自定义背景：相册选择、裁剪、预览、应用、清除。
2. 用亮色、暗色、复杂纹理三类背景做可读性人工验收。
3. 补最近使用背景。
4. 增加内置真实背景素材。
5. 做拖拽缩放裁剪。
6. 再考虑主色提取和视差。

不要先做主色提取和推荐机制。它们容易影响语义色稳定性，必须等基础背景链路和可读性验收稳定后再做。

