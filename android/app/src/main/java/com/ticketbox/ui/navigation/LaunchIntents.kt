package com.ticketbox.ui.navigation

/**
 * 启动器/系统分享进入 App 的「意图请求」领域模型 + 纯解析逻辑。
 *
 * 这里**不依赖** `android.content.Intent` / `android.net.Uri`：framework 取值
 * （`EXTRA_STREAM`、`clipData`、shortcut extra 字符串）由 [MainActivity] 这层
 * 边界胶水读出后，转成纯 JVM 输入交给这里裁决。好处是路由决策可在 Robolectric-free
 * 的单测里覆盖（unit test 下 `android.net.Uri` 会抛 not-mocked）。
 *
 * 解析结果交给 `MainShell` 的 LaunchedEffect 消费：
 *  - [LaunchIntentRequest.ShareImages] → 待确认 tab + 走现有上传链（在线-only，多图顺序上传）。
 *  - [LaunchIntentRequest.Navigate] → 切到目标 tab（必要时附带一次性动作，如自动打开记一笔表单）。
 */
// public（非 internal）：作为公开 composable [TicketboxApp] 的参数类型出现，
// Kotlin 不允许 public API 暴露 internal 类型。本模块是 application 模块、无外部消费方，
// 故 public 与 internal 实际等效，这里取 public 仅为满足该可见性约束。
sealed interface LaunchIntentRequest {
    /** 系统分享（ACTION_SEND / ACTION_SEND_MULTIPLE，image/*）带进来的一张或多张图。 */
    data class ShareImages(val uris: List<String>) : LaunchIntentRequest

    /** 启动器静态 shortcut 指定的导航目标。 */
    data class Navigate(val target: ShortcutTarget) : LaunchIntentRequest
}

/** 启动器静态 shortcut 的三个目标（与 `res/xml/shortcuts.xml` 一一对应）。
 *  public 同 [LaunchIntentRequest]：经 Navigate 间接出现在公开 composable 签名里。 */
enum class ShortcutTarget(val id: String) {
    /** 传小票：切到待确认 tab 并立即拉起系统图片选择，复用上传链。 */
    UploadReceipt("upload_receipt"),

    /** 记一笔：切到账本 tab 并自动打开「记一笔」手动记账表单。 */
    ManualEntry("manual_entry"),

    /** 去确认：切到待确认 tab。 */
    ReviewPending("review_pending"),
}

/**
 * 系统分享 Intent 的 action 常量（避免在边界层硬编码字面量，也便于单测引用）。
 */
internal object LaunchIntentActions {
    const val ACTION_SEND = "android.intent.action.SEND"
    const val ACTION_SEND_MULTIPLE = "android.intent.action.SEND_MULTIPLE"
}

/**
 * 启动器 shortcut 通过 extra 携带的目标标识 key。data uri / category 都不用，
 * 只用一个显式 extra，避免与系统/分享语义混淆。
 */
internal const val EXTRA_SHORTCUT_TARGET = "com.ticketbox.shortcut.target"

/**
 * 启动器静态 shortcut 的自定义 action（`res/xml/shortcuts.xml` 与 MainActivity
 * 的 intent-filter 共用）。**用 action 而非 targetPackage**：本项目 internal flavor
 * 带 `.internal` 的 applicationIdSuffix，硬编码 targetPackage 会在该变体下无法解析、
 * 静态快捷方式静默丢失；action-only intent 在本 App 内解析、跨 flavor 稳定。
 */
internal const val ACTION_SHORTCUT = "com.ticketbox.action.SHORTCUT"

/**
 * 把一次「分享/shortcut」入口归一成 [LaunchIntentRequest]。纯函数：
 *
 * @param action          Intent.action（可空）。
 * @param mimeType        Intent.type（可空）；只处理 image/*。
 * @param streamUris      从 EXTRA_STREAM（单/多）+ clipData 抽出的 uri 字符串（边界层已 null/空过滤前的原始集）。
 * @param shortcutTarget  shortcut extra 携带的目标标识（可空）。
 *
 * 裁决顺序：先看 shortcut（启动器静态入口优先、确定性最强）；再看分享 action + image 图。
 * 不匹配任何已知入口 → null（普通 MAIN/LAUNCHER 冷启动，不做特殊路由）。
 */
internal fun resolveLaunchIntent(
    action: String?,
    mimeType: String?,
    streamUris: List<String?>,
    shortcutTarget: String?,
): LaunchIntentRequest? {
    resolveShortcutTarget(shortcutTarget)?.let { return LaunchIntentRequest.Navigate(it) }

    if (!isImageShareAction(action, mimeType)) return null
    val cleanUris = sanitizeUriList(streamUris)
    if (cleanUris.isEmpty()) return null
    return LaunchIntentRequest.ShareImages(cleanUris)
}

/** 把 shortcut extra 字符串映射到 [ShortcutTarget]；未知/空 → null。 */
internal fun resolveShortcutTarget(target: String?): ShortcutTarget? {
    val trimmed = target?.trim().orEmpty()
    if (trimmed.isEmpty()) return null
    return ShortcutTarget.entries.firstOrNull { it.id == trimmed }
}

/** action 是 SEND / SEND_MULTIPLE 且 MIME 落在 image/* 才算图片分享。 */
private fun isImageShareAction(action: String?, mimeType: String?): Boolean {
    val isSend = action == LaunchIntentActions.ACTION_SEND || action == LaunchIntentActions.ACTION_SEND_MULTIPLE
    if (!isSend) return false
    // 分享面板会按我们声明的 image/* filter 过滤来源，但 type 仍可能为 null（少数 app
    // 不带 MIME）。声明的 filter 是第一道门，这里再用 type 兜一层：null 放行（信任系统
    // 已按 filter 匹配），非 image/* 拒绝。
    val type = mimeType?.trim()?.lowercase()
    return type == null || type.isEmpty() || type.startsWith("image/")
}

/** 去 null、去空白、去重并保序——多图分享里重复 uri 不重复上传。 */
private fun sanitizeUriList(uris: List<String?>): List<String> {
    val seen = LinkedHashSet<String>()
    for (raw in uris) {
        val value = raw?.trim().orEmpty()
        if (value.isNotEmpty()) seen.add(value)
    }
    return seen.toList()
}
