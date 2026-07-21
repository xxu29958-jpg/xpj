package com.ticketbox.ui.theme

import androidx.compose.material3.Typography
import com.ticketbox.ui.design.AppTypeScale
import com.ticketbox.ui.design.asTextStyle

/**
 * Material3 角色只映射 [AppTypeScale]，页面与组件只能消费
 * `MaterialTheme.typography`，不得自行写字号或行高。
 */
val TicketboxTypography: Typography = Typography(
    displayLarge = AppTypeScale.amountHero.asTextStyle(),
    displayMedium = AppTypeScale.pageHero.asTextStyle(),
    displaySmall = AppTypeScale.pageTitle.asTextStyle(),
    headlineLarge = AppTypeScale.headline.asTextStyle(),
    headlineMedium = AppTypeScale.headlineQuiet.asTextStyle(),
    headlineSmall = AppTypeScale.sectionTitle.asTextStyle(),
    titleLarge = AppTypeScale.sectionTitle.asTextStyle(),
    titleMedium = AppTypeScale.bodyStrong.asTextStyle(),
    titleSmall = AppTypeScale.bodyStrong.asTextStyle(),
    bodyLarge = AppTypeScale.body.asTextStyle(),
    bodyMedium = AppTypeScale.caption.asTextStyle(),
    bodySmall = AppTypeScale.captionCompact.asTextStyle(),
    labelLarge = AppTypeScale.control.asTextStyle(),
    labelMedium = AppTypeScale.controlCompact.asTextStyle(),
    labelSmall = AppTypeScale.controlCompact.asTextStyle(),
)
