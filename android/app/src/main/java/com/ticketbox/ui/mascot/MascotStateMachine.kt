package com.ticketbox.ui.mascot

/**
 * 夹夹(吉祥物)的展示状态——与 docs/roadmap/MASCOT_BRIEF.md §4 的状态谱一一对应。
 *
 * 两类:
 * - **环境态**(level,持续条件在则在):[Dozing] 空态闲置打盹 / [Juggling] 加载同步抛硬币 /
 *   [Searching] 搜索无果举放大镜 / [Neutral] 默认清醒。
 * - **一次性反应**(one-shot,事件触发、播完自动回落环境态):其余全部。
 *
 * 本层是纯 Kotlin、零依赖(不 import Rive/Compose/Android):后续 Rive 集成
 * ([[ADR-0048]],等原画与 accept)把这里的状态映射为 Rive 状态机 input;在那之前
 * 这层先行可测,也是降级方案(静态主题化空态)共用的事件→状态真相源。
 */
enum class MascotState {
    Neutral,
    Dozing,
    Juggling,
    Searching,
    Greeting,
    ClampCheer,
    Dismissive,
    Celebrating,
    Stretching,
    Tickled,
    Shocked,
}

/** app 事件→夹夹反应的输入。edge 事件触发 one-shot;level 事件维护环境态。 */
sealed interface MascotEvent {
    /** 确认一笔成功(「夹住」)。 */
    data object ExpenseConfirmed : MascotEvent

    /** 忽略/驳回一笔。 */
    data object ExpenseDismissed : MascotEvent

    /** 目标达成 / 欠款清零(里程碑,最高优先级,对位 milestone-feedback 缺口)。 */
    data object MilestoneReached : MascotEvent

    /** 下拉刷新开始。 */
    data object PullToRefresh : MascotEvent

    /** 用户戳了夹夹一下。 */
    data object Poked : MascotEvent

    /** 大额/超支提醒浮现。 */
    data object LargeExpenseAlert : MascotEvent

    /** 进入一个还没有任何账目的账本。 */
    data object EmptyLedgerEntered : MascotEvent

    /** 同步/加载进行中(level)。 */
    data class SyncActive(val active: Boolean) : MascotEvent

    /** 搜索无果屏可见(level)。 */
    data class EmptySearchShown(val shown: Boolean) : MascotEvent

    /** 空态屏(无数据闲置)可见(level)。 */
    data class IdleEmptyShown(val shown: Boolean) : MascotEvent
}

/**
 * 事件→状态的纯 reducer。时间全部由调用方注入([onEvent]/[onTick] 的 nowMillis),
 * 自身不取时钟,便于单测与未来接 Compose frame clock / Rive advance。
 *
 * 规则(全部有测试钉住):
 * 1. one-shot 在播期间,同名事件忽略(动画播完整,连续审阅快速确认不抖动);
 * 2. 不同 one-shot 按优先级抢占:[Celebrating] > [Shocked] > 其余;同级后到者替换;
 * 3. one-shot 到时自动回落环境态;
 * 4. 环境态分层:[Juggling](同步) > [Searching](无果) > [Dozing](空态) > [Neutral]。
 */
class MascotStateMachine {
    private var syncActive = false
    private var emptySearchShown = false
    private var idleEmptyShown = false
    private var oneShot: MascotState? = null
    private var oneShotExpiresAt = 0L

    /** 喂一个事件,返回此刻应展示的状态。 */
    fun onEvent(event: MascotEvent, nowMillis: Long): MascotState {
        when (event) {
            is MascotEvent.SyncActive -> syncActive = event.active
            is MascotEvent.EmptySearchShown -> emptySearchShown = event.shown
            is MascotEvent.IdleEmptyShown -> idleEmptyShown = event.shown
            MascotEvent.ExpenseConfirmed -> trigger(MascotState.ClampCheer, nowMillis)
            MascotEvent.ExpenseDismissed -> trigger(MascotState.Dismissive, nowMillis)
            MascotEvent.MilestoneReached -> trigger(MascotState.Celebrating, nowMillis)
            MascotEvent.PullToRefresh -> trigger(MascotState.Stretching, nowMillis)
            MascotEvent.Poked -> trigger(MascotState.Tickled, nowMillis)
            MascotEvent.LargeExpenseAlert -> trigger(MascotState.Shocked, nowMillis)
            MascotEvent.EmptyLedgerEntered -> trigger(MascotState.Greeting, nowMillis)
        }
        return onTick(nowMillis)
    }

    /** 推进时间(过期回落),返回此刻应展示的状态。宿主按帧/秒级调用皆可。 */
    fun onTick(nowMillis: Long): MascotState = activeOneShot(nowMillis) ?: ambient()

    private fun trigger(state: MascotState, nowMillis: Long) {
        val active = activeOneShot(nowMillis)
        if (active != null) {
            if (state == active) return
            if (priorityOf(state) < priorityOf(active)) return
        }
        oneShot = state
        oneShotExpiresAt = nowMillis + ONE_SHOT_DURATION_MS.getValue(state)
    }

    private fun activeOneShot(nowMillis: Long): MascotState? =
        oneShot?.takeIf { nowMillis < oneShotExpiresAt }

    private fun ambient(): MascotState = when {
        syncActive -> MascotState.Juggling
        emptySearchShown -> MascotState.Searching
        idleEmptyShown -> MascotState.Dozing
        else -> MascotState.Neutral
    }

    companion object {
        /** one-shot 播放时长(毫秒)。Rive 侧动画时长以此为准对齐(brief §4)。 */
        val ONE_SHOT_DURATION_MS: Map<MascotState, Long> = mapOf(
            MascotState.Greeting to 2_400L,
            MascotState.ClampCheer to 1_800L,
            MascotState.Dismissive to 1_500L,
            MascotState.Celebrating to 3_600L,
            MascotState.Stretching to 1_200L,
            MascotState.Tickled to 1_200L,
            MascotState.Shocked to 2_400L,
        )

        /** 抢占优先级:里程碑庆祝最高,超支吃惊次之,日常反应同级互换。 */
        fun priorityOf(state: MascotState): Int = when (state) {
            MascotState.Celebrating -> 3
            MascotState.Shocked -> 2
            else -> 1
        }

        /**
         * MascotState → Rive 状态机 state 名,命名真相源 = MASCOT_BRIEF.md §7.3。
         * [MascotState.Neutral] 是表里没有的隐含清醒基线,命名对齐 idle_sleep 取
         * `idle_awake`。绑定层(ADR-0048 集成 PR)只做这张表的查表,不再自创名字。
         */
        val RIVE_STATE_NAME: Map<MascotState, String> = mapOf(
            MascotState.Neutral to "idle_awake",
            MascotState.Dozing to "idle_sleep",
            MascotState.Juggling to "sync_coin_loop",
            MascotState.Searching to "search_empty",
            MascotState.Greeting to "empty_welcome",
            MascotState.ClampCheer to "confirm_success",
            MascotState.Dismissive to "review_reject",
            MascotState.Celebrating to "milestone_celebrate",
            MascotState.Stretching to "pull_refresh_stretch",
            MascotState.Tickled to "tap_giggle",
            MascotState.Shocked to "overspend_alert",
        )
    }
}
