package com.ticketbox.ui.mascot

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * 钉死 one-shot 规则(与 MascotStateMachine KDoc 同源):同名忽略不延长 /
 * 优先级抢占 / 到时回落。环境态分层在 MascotStateMachineAmbientTest。
 * 时长常量直接引用生产 map——时长改了测试跟着走,规则翻了测试翻红。
 */
class MascotStateMachineTest {
    private val machine = MascotStateMachine()

    private fun cheerDuration() =
        MascotStateMachine.ONE_SHOT_DURATION_MS.getValue(MascotState.ClampCheer)

    @Test
    fun confirmTriggersClampCheerThenFallsBackToNeutral() {
        assertEquals(MascotState.ClampCheer, machine.onEvent(MascotEvent.ExpenseConfirmed, 1_000L))
        assertEquals(MascotState.ClampCheer, machine.onTick(1_000L + cheerDuration() - 1))
        assertEquals(MascotState.Neutral, machine.onTick(1_000L + cheerDuration()))
    }

    @Test
    fun sameOneShotRetriggerWhileActiveIsIgnoredAndDoesNotExtend() {
        machine.onEvent(MascotEvent.ExpenseConfirmed, 1_000L)
        machine.onEvent(MascotEvent.ExpenseConfirmed, 1_500L)
        // 没被延长:仍按第一次的到期时间回落。
        assertEquals(MascotState.Neutral, machine.onTick(1_000L + cheerDuration()))
    }

    @Test
    fun milestoneCelebrationPreemptsCheer() {
        machine.onEvent(MascotEvent.ExpenseConfirmed, 1_000L)
        assertEquals(MascotState.Celebrating, machine.onEvent(MascotEvent.MilestoneReached, 1_200L))
    }

    @Test
    fun cheerDoesNotPreemptCelebration() {
        machine.onEvent(MascotEvent.MilestoneReached, 1_000L)
        assertEquals(MascotState.Celebrating, machine.onEvent(MascotEvent.ExpenseConfirmed, 1_200L))
    }

    @Test
    fun shockPreemptsCheerButNotCelebration() {
        machine.onEvent(MascotEvent.ExpenseConfirmed, 1_000L)
        assertEquals(MascotState.Shocked, machine.onEvent(MascotEvent.LargeExpenseAlert, 1_100L))
        machine.onEvent(MascotEvent.MilestoneReached, 1_200L)
        assertEquals(MascotState.Celebrating, machine.onEvent(MascotEvent.LargeExpenseAlert, 1_300L))
    }

    @Test
    fun samePriorityLaterOneShotReplacesEarlier() {
        machine.onEvent(MascotEvent.ExpenseConfirmed, 1_000L)
        assertEquals(MascotState.Dismissive, machine.onEvent(MascotEvent.ExpenseDismissed, 1_100L))
    }

    @Test
    fun tickBeforeExpiryKeepsOneShot() {
        machine.onEvent(MascotEvent.LargeExpenseAlert, 0L)
        assertEquals(MascotState.Shocked, machine.onTick(1L))
    }

    @Test
    fun allOneShotStatesHaveConfiguredDurations() {
        val oneShots = listOf(
            MascotState.Greeting,
            MascotState.ClampCheer,
            MascotState.Dismissive,
            MascotState.Celebrating,
            MascotState.Stretching,
            MascotState.Tickled,
            MascotState.Shocked,
        )
        // getValue 抛 NoSuchElementException 即红:新增 one-shot 必须配时长。
        oneShots.forEach { state ->
            assertTrue(
                MascotStateMachine.ONE_SHOT_DURATION_MS.getValue(state) > 0,
                "duration for $state",
            )
        }
    }

    @Test
    fun riveStateNamesCoverEveryStateUniquely() {
        val names = MascotStateMachine.RIVE_STATE_NAME
        // 每个枚举态都有 Rive 名(新增状态必须同步 brief §7.3 命名),且无重名。
        assertEquals(MascotState.entries.size, names.size)
        assertEquals(names.size, names.values.toSet().size)
        MascotState.entries.forEach { state -> assertTrue(names.getValue(state).isNotBlank()) }
    }
}
