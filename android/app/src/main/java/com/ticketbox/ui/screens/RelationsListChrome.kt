package com.ticketbox.ui.screens

import androidx.compose.runtime.Composable

/**
 * Lets the same data-driven list render either as a secondary drill-in page or
 * as a view inside the primary obligations domain.
 *
 * W2-C 主域嵌入态（[embeddedInDomain]）：shell 已有域名，列表不再渲染大标题/副标题/头部
 * 动作；[topChrome]（tabs + 单主 CTA）作为列表首项随内容滚动，[domainNavigation] 沉到列表尾，
 * 让真实往来内容占上半屏。
 */
data class RelationsListChrome(
    val title: String,
    val subtitle: String?,
    val backText: String,
    val onBack: (() -> Unit)?,
    val domainNavigation: (@Composable () -> Unit)? = null,
    val embeddedInDomain: Boolean = false,
    val topChrome: (@Composable () -> Unit)? = null,
)
