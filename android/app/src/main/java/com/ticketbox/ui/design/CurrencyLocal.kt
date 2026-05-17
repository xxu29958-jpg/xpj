package com.ticketbox.ui.design

import androidx.compose.runtime.staticCompositionLocalOf
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay

/**
 * 当前 UI 渲染金额时应使用的显示币种代码。
 *
 * 由 [com.ticketbox.ui.theme.TicketboxTheme] 在 setContent 顶层提供，
 * 用于新账单默认原始币种、币种选择 UI 等用户偏好。
 *
 * 用 `staticCompositionLocalOf` 而不是 `compositionLocalOf`：
 * 币种切换需要重组所有读取它的页面，static 版的更新成本更低，
 * 因为它不参与依赖追踪（切换币种本身就需要全屏重绘）。
 */
val LocalCurrencyCode = staticCompositionLocalOf { CurrencyCode.Default }

/**
 * 当前 UI 渲染后端 home amount 时应使用的上下文。
 *
 * 全局金额、统计、预算、报表和 Goals 均使用后端返回/聚合后的 home amount；
 * 前端不保存汇率、不请求外部汇率 API，也不在本机做外币折算。
 */
val LocalCurrencyDisplay = staticCompositionLocalOf { CurrencyDisplay.Base }
