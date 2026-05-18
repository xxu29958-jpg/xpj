package com.ticketbox.ui.design

import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.Easing
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.FiniteAnimationSpec
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.tween

/**
 * 运动 token —— 时长 + 缓动曲线，所有动画都必须从这里挑组合，
 * 不允许在调用处自己拼 `tween(123, MyCustomEasing)`。
 *
 * 四档时长（与 shared/tokens.css 的 --motion-fast/normal/slow/background 对齐）：
 *  - [fastMillis] 120ms：按钮按下、chip 选中、tab 切换图标颜色
 *  - [normalMillis] 220ms：卡片高度变化、bottom-bar weight 调整、AnimatedContent 进/出
 *  - [slowMillis] 320ms：modal 出入、page 切换、跨场景的 morph
 *  - [backgroundMillis] 420ms：背景渐变、parallax、不抢主操作焦点的环境动画
 *
 * 三档缓动：
 *  - [easeStandard]：M3 emphasized 默认，先慢后快收尾。覆盖 90% 用例
 *  - [easeEmphasized]：先快后慢，强调结束位置。用于"出现"动画
 *  - [easeAccelerate]：纯加速，元素离开屏幕时用，无需关心 land 状态
 */
object AppMotion {
    const val fastMillis: Int = 120
    const val normalMillis: Int = 220
    const val slowMillis: Int = 320
    const val backgroundMillis: Int = 420

    /** v0.10 拖拽拾起动效时长（DraggableReorderColumn 等）。 */
    const val dragLiftMillis: Int = 160

    /** v0.10 左右滑揭示动效时长（SwipeableActionRow 等）。 */
    const val swipeRevealMillis: Int = 180

    /** M3 emphasized standard —— 适合大部分状态切换（hover、selection、show/hide）。 */
    val easeStandard: Easing = CubicBezierEasing(0.2f, 0f, 0f, 1f)

    /** 强调结束位置——元素从无到有、滑入屏幕等「进入」动作。 */
    val easeEmphasized: Easing = CubicBezierEasing(0.05f, 0.7f, 0.1f, 1f)

    /** 加速退场——元素脱离视野（dismiss、关闭弹窗后半段）。 */
    val easeAccelerate: Easing = CubicBezierEasing(0.3f, 0f, 1f, 1f)

    /** 线性——只用于 loading 旋转、shimmer 这类等速场景。 */
    val easeLinear: Easing = LinearEasing

    /** v0.10 回弹/超调——拾起后落位、按钮按下回弹等"有重量感"的反馈。 */
    val easeOvershoot: Easing = CubicBezierEasing(0.34f, 1.56f, 0.64f, 1f)

    /** Material 3 默认 `FastOutSlowInEasing` 的别名；个别 M3 组件需要它的精确曲线。 */
    val easeM3Default: Easing = FastOutSlowInEasing

    /**
     * 标准状态切换 spec（duration + easeStandard）。
     * 80% 的 `tween(...)` 都应该改用 [standardSpec]。
     */
    fun <T> standardSpec(durationMillis: Int = normalMillis): FiniteAnimationSpec<T> =
        tween(durationMillis = durationMillis, easing = easeStandard)

    /** 强调进入。配合 [easeEmphasized]。 */
    fun <T> emphasizedSpec(durationMillis: Int = normalMillis): FiniteAnimationSpec<T> =
        tween(durationMillis = durationMillis, easing = easeEmphasized)

    /** 加速退场。配合 [easeAccelerate]。 */
    fun <T> exitSpec(durationMillis: Int = fastMillis): FiniteAnimationSpec<T> =
        tween(durationMillis = durationMillis, easing = easeAccelerate)
}
