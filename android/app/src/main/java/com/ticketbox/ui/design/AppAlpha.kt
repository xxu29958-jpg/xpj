package com.ticketbox.ui.design

/**
 * 语义化透明度档位（7 档），给 ``Color.copy(alpha = …)`` 用。
 *
 * 设计依据：扫描全 Android 表现层现有 ``.copy(alpha = 0.x)`` 字面量分布（约 190 处）取
 * 各众数群锚定，而非凭空拍数值，便于把散落字面量逐步收敛到这 7 档而**不改观感**：
 * - 0.10 / 0.16 —— 最淡的背板/分隔群（0.06–0.18）
 * - 0.24       —— 单一最强众数群之一（7 次）
 * - 0.42       —— 中段（0.34–0.48）
 * - 0.58       —— 偏实（0.54–0.62）
 * - 0.72       —— 全表最高众数（8 次，0.70–0.72 主峰）
 * - 0.86       —— 近实心群众数（0.86–0.92）
 *
 * 用法（语义优先，不是"按数字挑"）：
 * - [faint]  极淡叠层 / hairline 暗角（如英雄卡顶部高光）
 * - [subtle] 轻背板 / 极弱分隔
 * - [soft]   柔背景填充 / 弱边框
 * - [medium] 中等强调边框 / 半禁用前景
 * - [strong] 偏实前景 / 次级图标 tint
 * - [heavy]  接近实心的容器/边框
 * - [opaque] 几乎不透明的容器（仍留一丝背景层次）
 *
 * 注意：这是**提供档位**，不做 big-bang 全量替换（升级地图已砍该做法）。新代码优先用本档位；
 * 存量逐步迁移，由 ``backend/scripts/_audit_android_alpha_ratchet.py`` 把字面量计数 ratchet 只降不升。
 * 艺术层（主题/背景/庆祝动画等，见 ratchet lane 头注释的豁免清单）保留自定数值，不强迁。
 *
 * 取值用 [Float]（``Color.copy(alpha=)`` 接受 Float），不带 ``.dp`` 等单位。纯常量，可单测。
 */
object AppAlpha {
    /** 0.10 —— 极淡叠层 / 暗角高光。 */
    const val faint: Float = 0.10f

    /** 0.16 —— 轻背板 / 极弱分隔。 */
    const val subtle: Float = 0.16f

    /** 0.24 —— 柔背景填充 / 弱边框。 */
    const val soft: Float = 0.24f

    /** 0.42 —— 中等强调边框 / 半禁用前景。 */
    const val medium: Float = 0.42f

    /** 0.58 —— 偏实前景 / 次级图标 tint。 */
    const val strong: Float = 0.58f

    /** 0.72 —— 接近实心的容器 / 边框（全表最高众数）。 */
    const val heavy: Float = 0.72f

    /** 0.86 —— 几乎不透明的容器（仍留一丝背景层次）。 */
    const val opaque: Float = 0.86f
}
