package com.ticketbox.ui.navigation

import android.content.Context
import androidx.lifecycle.ViewModelStore
import androidx.lifecycle.ViewModelStoreOwner
import com.ticketbox.data.local.BackgroundImageStore
import com.ticketbox.data.repository.ExpenseCorrectionConnectedFixture
import com.ticketbox.data.repository.LocalBackgroundImageRepository
import com.ticketbox.data.repository.toDomain
import com.ticketbox.domain.model.ExpenseCorrectionDraft
import com.ticketbox.viewmodel.appearanceViewModelFactory
import com.ticketbox.viewmodel.categoryRulesViewModelFactory
import com.ticketbox.viewmodel.merchantAliasViewModelFactory
import com.ticketbox.viewmodel.settingsViewModelFactory
import java.io.Closeable
import kotlinx.coroutines.flow.first

/** Only prepares dependencies and a real Room recovery row; all navigation stays in MainNavGraph. */
internal class FactEntryNavigationHarness(context: Context,
    wrapApi: (com.ticketbox.data.remote.ApiService) -> com.ticketbox.data.remote.ApiService = { it },
) : Closeable {
    val fixture = ExpenseCorrectionConnectedFixture(context, wrapApi)
    private val graph = fixture.reopen()
    val shell = MainShellState()
    val models = object : ViewModelStoreOwner {
        override val viewModelStore = ViewModelStore()
    }
    val screenFactory = MainScreenFactory(
        MainFeatureRepositories(
            repository = graph.expenseRepository,
            uploadIntents = fixture.uploadIntents,
            ledgerRepository = graph.ledgerRepository,
            recurringRepository = graph.recurringRepository,
            budgetRepository = graph.budgetRepository,
            reportsRepository = graph.reportsRepository,
            goalEditRepository = graph.goalEditRepository,
            ruleRepository = graph.ruleRepository,
            incomePlanRepository = graph.incomePlanRepository,
            debtRepository = graph.debtRepository,
            debtCreationRepository = graph.debtCreationRepository,
            debtWriteRepository = graph.debtWriteRepository,
            repaymentDraftRepository = graph.repaymentDraftRepository,
            outboxRepository = fixture.outbox,
            tagRepository = graph.tagRepository,
            categoryPreferenceRepository = graph.categoryPreferenceRepository,
        ),
        MainScreenViewModelFactories(
            settingsViewModelFactory = settingsViewModelFactory(graph.expenseRepository, fixture.settingsStore),
            categoryRulesViewModelFactory = categoryRulesViewModelFactory(graph.ruleRepository, graph.expenseRepository),
            merchantAliasViewModelFactory = merchantAliasViewModelFactory(graph.merchantRepository, graph.expenseRepository),
            appearanceViewModelFactory = appearanceViewModelFactory(fixture.settingsStore,
                LocalBackgroundImageRepository(BackgroundImageStore(context))),
        ),
    )

    suspend fun saveFailedCorrection(): Map<String, String?> {
        val repository = graph.expenseRepository
        val binding = requireNotNull(repository.observeCorrections().first().access).binding
        val id = repository.submitCorrection(binding, fixture.network.current.toDomain(),
            ExpenseCorrectionDraft("导航核对原提交", note = "返回后仍保留原提交")).getOrThrow()
        fixture.outbox.markFailed(id, "correction_delivery_unknown")
        return fixture.stored().single()
    }

    override fun close() = fixture.close()
}
