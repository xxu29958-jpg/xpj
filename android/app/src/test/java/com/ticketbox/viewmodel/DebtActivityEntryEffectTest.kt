package com.ticketbox.viewmodel

import android.app.Application
import androidx.compose.runtime.AbstractApplier
import androidx.compose.runtime.BroadcastFrameClock
import androidx.compose.runtime.Composition
import androidx.compose.runtime.Recomposer
import androidx.compose.runtime.mutableStateOf
import com.ticketbox.data.repository.DebtActivityQueries
import com.ticketbox.domain.model.DebtActivity
import com.ticketbox.domain.model.DebtActivityPage
import com.ticketbox.ui.screens.DebtDetailEffects
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals

@OptIn(ExperimentalCoroutinesApi::class)
@RunWith(RobolectricTestRunner::class)
@Config(application = Application::class, sdk = [35])
class DebtActivityEntryEffectTest {
    private val dispatcher = StandardTestDispatcher()

    @BeforeTest fun setUp() { Dispatchers.setMain(dispatcher) }
    @AfterTest fun tearDown() { Dispatchers.resetMain() }

    @Test
    fun sameDebtReentryReadsRemoteProposalChangesWithoutRefreshingOnRecomposition() = runTest(dispatcher) {
        var reads = 0
        var remoteProposal = sampleMemberProposal()
        val activity = DebtActivityViewModel(DebtActivityQueries { task, _, _ ->
            reads++
            Result.success(DebtActivityPage(task.debtPublicId, "CNY", listOf(
                DebtActivity("proposal_created", remoteProposal.publicId, remoteProposal.createdAt,
                    actorDisplayName = null, actorIsYou = false, proposal = remoteProposal),
            ), page = 1, pageSize = 20, total = 1))
        })
        val proposalActions = ProposalTestActions(listResult = Result.success(listOf(remoteProposal)))
        val proposals = MemberRepaymentProposalViewModel(proposalActions)
        val detail = DebtDetailViewModel(FakeDebtActions(), FakeDebtWriteActions())
        val state = mutableStateOf(DebtDetailUiState(
            binding = memberDebtTask("d1").binding, debt = sampleMemberDebt(),
        ))
        val frames = BroadcastFrameClock()
        val recomposer = Recomposer(coroutineContext + frames)
        val runner = launch(frames) { recomposer.runRecomposeAndApplyChanges() }
        fun enter() = Composition(EffectsOnlyApplier(), recomposer).also { composition ->
            composition.setContent {
                DebtDetailEffects(state.value, MemberProposalUiState(), detail, proposals, activity)
            }
        }
        var composition = enter()
        try {
            advanceUntilIdle()
            assertEquals(1, reads)
            assertEquals("p1", activity.state.value.items.single().publicId)
            state.value = state.value.copy(isLoading = true)
            runCurrent()
            frames.sendFrame(1L)
            advanceUntilIdle()
            assertEquals(1, reads)
            composition.dispose()
            assertEquals("p1", activity.state.value.items.single().publicId)
            remoteProposal = sampleMemberProposal(publicId = "p2")
            proposalActions.listResult = Result.success(listOf(remoteProposal))
            composition = enter()
            advanceUntilIdle()
            assertEquals("p2", proposals.state.value.proposals.single().publicId)
            assertEquals(2, reads)
            assertEquals("p2", activity.state.value.items.single().publicId)
        } finally {
            composition.dispose()
            recomposer.close()
            runner.join()
        }
    }
}

/** The production effects have no UI nodes; Compose still owns entry/disposal and key changes. */
private class EffectsOnlyApplier : AbstractApplier<Unit>(Unit) {
    override fun insertTopDown(index: Int, instance: Unit) = Unit
    override fun insertBottomUp(index: Int, instance: Unit) = Unit
    override fun remove(index: Int, count: Int) = Unit
    override fun move(from: Int, to: Int, count: Int) = Unit
    override fun onClear() = Unit
}
