package com.ticketbox.ui.mascot

import kotlin.test.Test
import kotlin.test.assertEquals

/**
 * 钉死环境态规则:level 事件维护 + 分层(Juggling > Searching > Dozing > Neutral),
 * 以及 one-shot 回落进环境态而非硬回 Neutral。one-shot 抢占规则在
 * MascotStateMachineTest。
 */
class MascotStateMachineAmbientTest {
    private val machine = MascotStateMachine()

    @Test
    fun oneShotFallsBackToAmbientDozingNotNeutral() {
        val duration = MascotStateMachine.ONE_SHOT_DURATION_MS.getValue(MascotState.ClampCheer)
        machine.onEvent(MascotEvent.IdleEmptyShown(shown = true), 0L)
        machine.onEvent(MascotEvent.ExpenseConfirmed, 1_000L)
        assertEquals(MascotState.Dozing, machine.onTick(1_000L + duration))
    }

    @Test
    fun syncActiveShowsJugglingUntilCleared() {
        assertEquals(MascotState.Juggling, machine.onEvent(MascotEvent.SyncActive(active = true), 0L))
        assertEquals(MascotState.Neutral, machine.onEvent(MascotEvent.SyncActive(active = false), 1L))
    }

    @Test
    fun ambientLayeringSyncBeatsSearchBeatsDozing() {
        machine.onEvent(MascotEvent.IdleEmptyShown(shown = true), 0L)
        machine.onEvent(MascotEvent.EmptySearchShown(shown = true), 0L)
        assertEquals(MascotState.Juggling, machine.onEvent(MascotEvent.SyncActive(active = true), 0L))
        assertEquals(MascotState.Searching, machine.onEvent(MascotEvent.SyncActive(active = false), 1L))
        assertEquals(MascotState.Dozing, machine.onEvent(MascotEvent.EmptySearchShown(shown = false), 2L))
    }

    @Test
    fun pokeTriggersTickled() {
        assertEquals(MascotState.Tickled, machine.onEvent(MascotEvent.Poked, 0L))
    }

    @Test
    fun pullToRefreshStretchesThenFallsBack() {
        val duration = MascotStateMachine.ONE_SHOT_DURATION_MS.getValue(MascotState.Stretching)
        assertEquals(MascotState.Stretching, machine.onEvent(MascotEvent.PullToRefresh, 0L))
        assertEquals(MascotState.Neutral, machine.onTick(duration))
    }

    @Test
    fun emptyLedgerGreetsThenDozesOnIdleEmpty() {
        val duration = MascotStateMachine.ONE_SHOT_DURATION_MS.getValue(MascotState.Greeting)
        machine.onEvent(MascotEvent.IdleEmptyShown(shown = true), 0L)
        assertEquals(MascotState.Greeting, machine.onEvent(MascotEvent.EmptyLedgerEntered, 0L))
        assertEquals(MascotState.Dozing, machine.onTick(duration))
    }
}
