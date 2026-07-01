package com.ticketbox.ui.design

import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * 列表行密度档位。
 *
 * 此前列表行的内边距 / 间距靠各屏手写魔法数字（ExpenseCard 的
 * `if (isCompact) 10.dp else 14.dp` 一族），没有统一档位，长列表和稀疏卡片
 * 流挤在同一套数值上。这里把"行密度"收成三档语义：
 *   - [Comfortable] —— 待审核等需要呼吸感、卡片成流的面（强质感）。
 *   - [Standard]    —— 账本主列表等常态面（中等密度）。
 *   - [Compact]     —— 信息密集的紧凑面（更实）。
 *
 * 档位 → 具体尺寸由 [AppDensity.rowMetrics] 给出。新代码挑档位，不再手写数值。
 */
enum class AppListDensity { Comfortable, Standard, Compact }

/**
 * 一档密度下的行尺寸。四项覆盖一行卡片的主要留白：
 *   - [rowPadding]  行 / 卡片内边距。
 *   - [contentGap]  行内主要 section 之间的竖向间距。
 *   - [itemSpacing] 行内横向元素（图标 / 文本块 / 金额）之间的间距。
 *   - [labelGap]    主行 / 副行等细行之间的竖向间距。
 *   - [markSize]    分类标记 / 缩略标记尺寸。
 */
data class AppRowMetrics(
    val rowPadding: Dp,
    val contentGap: Dp,
    val itemSpacing: Dp,
    val labelGap: Dp,
    val markSize: Dp,
)

object AppDensity {
    /**
     * 档位 → 行尺寸。[Comfortable] / [Compact] 两档的数值锚定在 `ExpenseCard`
     * 既有的 Comfortable / Compact 取值上（迁移到 token 后渲染逐字节不变），
     * [Standard] 是夹在两者之间的新中档，供账本等主列表后续采纳。
     *
     * 四项均严格单调（Compact < Standard < Comfortable），保证档位之间真有
     * 可感知的密度差，不会出现"换了档位却没变"的死档。
     */
    fun rowMetrics(density: AppListDensity): AppRowMetrics = when (density) {
        AppListDensity.Comfortable -> AppRowMetrics(
            rowPadding = 14.dp,
            contentGap = 12.dp,
            itemSpacing = 12.dp,
            labelGap = 6.dp,
            markSize = 54.dp,
        )
        AppListDensity.Standard -> AppRowMetrics(
            rowPadding = 12.dp,
            contentGap = 10.dp,
            itemSpacing = 11.dp,
            labelGap = 5.dp,
            markSize = 42.dp,
        )
        AppListDensity.Compact -> AppRowMetrics(
            rowPadding = 10.dp,
            contentGap = 8.dp,
            itemSpacing = 10.dp,
            labelGap = 4.dp,
            markSize = 32.dp,
        )
    }
}
