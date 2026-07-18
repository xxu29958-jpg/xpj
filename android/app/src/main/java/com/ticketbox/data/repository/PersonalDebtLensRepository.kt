package com.ticketbox.data.repository

import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.domain.model.Debt
import com.ticketbox.security.SessionTokenStore

/**
 * Network adapter for server-authoritative viewer-personal Debt projections.
 *
 * Both reads remain session + selected-ledger bound. The backend alone resolves owner-relative
 * direction, member-counterparty mirroring, third-party exclusion, cross-ledger redaction, and
 * receivable de-duplication.
 */
internal class NetworkPersonalDebtLensActions(
    settingsStore: TicketboxSettingsStore,
    tokenStore: SessionTokenStore,
    apiProvider: ApiServiceProvider,
) : PersonalDebtLensActions {
    private val requestGuard = LedgerRequestGuard(settingsStore, tokenStore, apiProvider)
    private val errorHandler = NetworkErrorHandler(
        settingsStore = settingsStore,
        context = "Debt personal lens",
    )

    override suspend fun listPayables(): Result<List<Debt>> =
        errorHandler.safeCall {
            requestGuard.guardedCall { api ->
                api.debtPayables().items.map { it.toDomain() }
            }
        }

    override suspend fun listReceivables(): Result<List<Debt>> =
        errorHandler.safeCall {
            requestGuard.guardedCall { api ->
                api.debtReceivables().items.map { it.toDomain() }
            }
        }
}
