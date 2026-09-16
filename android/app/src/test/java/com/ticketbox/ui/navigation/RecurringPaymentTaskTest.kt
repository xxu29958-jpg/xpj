package com.ticketbox.ui.navigation

import androidx.lifecycle.SavedStateHandle
import com.ticketbox.data.remote.dto.RecurringOccurrenceDto
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.ui.screens.recurringItem
import com.ticketbox.viewmodel.RecurringOccurrenceUiState
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class RecurringPaymentTaskTest {
    private val access = LedgerAccessContext(
        LogicalSessionBinding("https://occurrence.example", "ledger-1", "owner", "session", "binding"),
        true,
    )

    @Test
    fun knownCurrencyCapturesMerchantPeriodAndSuggestedAmountWithoutFormFields() {
        val task = assertNotNull(recurringPaymentTask(loaded("JPY", 1200)))
        assertEquals(access.binding, task.binding)
        assertEquals("rec-1", task.seriesPublicId)
        assertEquals("2026-08", task.period)
        assertEquals("日元订阅", task.merchant)
        assertEquals("JPY", task.recordedCurrencyCode)
        assertEquals(1200L, task.suggestedAmountMinor)
        assertEquals("CNY", task.ledgerHomeCurrencyCode)
        assertTrue(task.clientRef.isNotBlank())
    }

    @Test
    fun unknownCurrencyClearsSuggestedAmount() {
        val task = assertNotNull(recurringPaymentTask(loaded(null, 1200)))
        assertNull(task.recordedCurrencyCode)
        assertNull(task.suggestedAmountMinor)
        assertEquals("日元订阅", task.merchant)
    }

    @Test
    fun samePeriodReusesTheExistingClientRef() {
        val first = assertNotNull(recurringPaymentTask(loaded("JPY", 1200)))
        val again = assertNotNull(recurringPaymentTask(loaded("JPY", 1200), first))
        assertEquals(first.clientRef, again.clientRef)
        val otherMonth = assertNotNull(recurringPaymentTask(loaded("JPY", 1200).copy(
            occurrence = loaded("JPY", 1200).occurrence?.copy(period = "2026-09"),
        ), first))
        assertNotEquals(first.clientRef, otherMonth.clientRef)
    }

    @Test
    fun admittedOutboxClientRefIsReusedWhenTheStoreMappingIsGone() {
        val restored = assertNotNull(recurringPaymentTask(loaded("JPY", 1200), admittedClientRef = "outbox-august"))
        assertEquals("outbox-august", restored.clientRef)
        val originWins = assertNotNull(
            recurringPaymentTask(
                loaded("JPY", 1200),
                remembered = restored.copy(clientRef = "store-ref"),
                admittedClientRef = "outbox-august",
            ),
        )
        assertEquals("outbox-august", originWins.clientRef)
        val focused = assertNotNull(
            recurringPaymentFocused(
                remembered = restored.copy(clientRef = "store-ref"),
                task = restored.copy(clientRef = "route-ref"),
                originClientRef = "outbox-august",
                state = loaded("JPY", 1200),
            ),
        )
        assertEquals("outbox-august", focused.clientRef)
        assertEquals(
            71L,
            preferredPaymentExpenseId(
                focused, 71L, RecurringPaymentIdentity(focused.binding, focused.seriesPublicId, focused.period),
            ),
        )
    }

    @Test
    fun missingLedgerHomeDoesNotInventATask() {
        assertNull(recurringPaymentTask(loaded("JPY", 1200).copy(ledgerHomeCurrencyCode = null)))
    }

    @Test
    fun unloadAndOtherSeriesFulfilmentKeepTheOriginalTaskUntilTheUserClosesIt() {
        val task = assertNotNull(recurringPaymentTask(loaded("JPY", 1200)))
        assertTrue(retainRecurringPaymentTask(task, userClosed = false, visible(resolved = false)))
        assertTrue(
            retainRecurringPaymentTask(
                task, userClosed = false,
                visible(binding = task.binding, series = null, period = null, state = null),
            ),
        )
        assertTrue(
            retainRecurringPaymentTask(
                task, userClosed = false, visible(period = "2026-09"),
            ),
        )
        assertTrue(
            retainRecurringPaymentTask(
                task, userClosed = false, visible(series = "rec-2", state = "fulfilled"),
            ),
        )
        assertTrue(
            !retainRecurringPaymentTask(
                task, userClosed = false, visible(state = "fulfilled"),
            ),
        )
        assertTrue(
            !retainRecurringPaymentTask(task, userClosed = true, visible(resolved = false)),
        )
        assertTrue(
            !retainRecurringPaymentTask(
                task, userClosed = false,
                visible(binding = task.binding.copy(ledgerId = "other")),
            ),
        )
    }

    @Test
    fun preferredPaymentOnlyPinsWhenTheVisibleOccurrenceIsTheOriginalTask() {
        val task = assertNotNull(recurringPaymentTask(loaded("JPY", 1200)))
        assertEquals(
            71L,
            preferredPaymentExpenseId(task, 71L, RecurringPaymentIdentity(task.binding, task.seriesPublicId, task.period)),
        )
        assertNull(preferredPaymentExpenseId(task, 71L, RecurringPaymentIdentity(task.binding, task.seriesPublicId, "2026-09")))
        assertNull(preferredPaymentExpenseId(task, 71L, RecurringPaymentIdentity(task.binding, "rec-2", task.period)))
        assertNull(
            preferredPaymentExpenseId(
                task, 71L, RecurringPaymentIdentity(task.binding.copy(ledgerId = "other"), task.seriesPublicId, task.period),
            ),
        )
        assertNull(preferredPaymentExpenseId(null, 71L, RecurringPaymentIdentity(task.binding, task.seriesPublicId, task.period)))
    }

    @Test
    fun unresolvedObservationsDoNotLookLikeAMissingCommandOrBindingChange() {
        assertTrue(!recurringPaymentObservationsReady(accessResolved = false, admittedResolved = false))
        assertTrue(!recurringPaymentObservationsReady(accessResolved = true, admittedResolved = false))
        assertTrue(recurringPaymentObservationsReady(accessResolved = true, admittedResolved = true))
        assertTrue(!recurringPaymentShowsBindingChanged(accessResolved = false, sameBinding = false))
        assertTrue(recurringPaymentShowsBindingChanged(accessResolved = true, sameBinding = false))
        assertTrue(!recurringPaymentShowsBindingChanged(accessResolved = true, sameBinding = true))
    }

    @Test
    fun draftStoreKeepsClearedAmountAndMerchantForTheSameClientRef() {
        val state = androidx.lifecycle.SavedStateHandle()
        val drafts = RecurringPaymentDraftStore(state)
        val task = assertNotNull(recurringPaymentTask(loaded("JPY", 1200)))
        drafts.write(
            RecurringPaymentDraft(
                clientRef = task.clientRef,
                amountText = "",
                currencyCode = "USD",
                merchant = "",
                category = "住房",
                note = "自填备注",
                expenseTime = "2026-08-20T10:00:00Z",
            ),
        )
        val restored = RecurringPaymentDraftStore(
            androidx.lifecycle.SavedStateHandle(state.keys().associateWith { state.get<Any?>(it) }),
        ).read(task.clientRef)
        assertEquals("", restored?.amountText)
        assertEquals("", restored?.merchant)
        assertEquals("USD", restored?.currencyCode)
        assertEquals("住房", restored?.category)
        assertEquals("自填备注", restored?.note)
        assertEquals("2026-08-20T10:00:00Z", restored?.expenseTime)
        drafts.removeDraft(task.clientRef)
        assertNull(drafts.read(task.clientRef))
        drafts.remember(task)
        drafts.write(
            RecurringPaymentDraft(
                clientRef = task.clientRef,
                amountText = "",
                currencyCode = "USD",
                merchant = "",
                category = "住房",
                note = "自填备注",
                expenseTime = "2026-08-20T10:00:00Z",
            ),
        )
        drafts.removeDraft(task.clientRef)
        assertNull(drafts.read(task.clientRef))
        assertEquals(task.clientRef, drafts.remembered(task.binding, task.seriesPublicId, task.period)?.clientRef)
        drafts.retireTask(task.clientRef)
        assertNull(drafts.remembered(task.binding, task.seriesPublicId, task.period))
    }

    @Test
    fun rememberedAugustIdentitySurvivesALaterSeptemberTask() {
        val august = assertNotNull(recurringPaymentTask(loaded("JPY", 1200)))
        val septemberState = loaded("JPY", 1200).copy(
            occurrence = loaded("JPY", 1200).occurrence?.copy(period = "2026-09"),
        )
        val september = assertNotNull(recurringPaymentTask(septemberState, august))
        assertNotEquals(august.clientRef, september.clientRef)
        val again = assertNotNull(recurringPaymentTask(loaded("JPY", 1200), september, remembered = august))
        assertEquals(august.clientRef, again.clientRef)
        assertEquals("2026-08", again.period)
    }

    @Test
    fun draftStoreFindsTheOriginalTaskByBindingSeriesAndPeriod() {
        val state = androidx.lifecycle.SavedStateHandle()
        val drafts = RecurringPaymentDraftStore(state)
        val august = assertNotNull(recurringPaymentTask(loaded("JPY", 1200)))
        val september = assertNotNull(recurringPaymentTask(loaded("JPY", 1200).copy(
            occurrence = loaded("JPY", 1200).occurrence?.copy(period = "2026-09"),
        ), august))
        drafts.remember(august)
        drafts.remember(september)
        drafts.write(
            RecurringPaymentDraft(
                clientRef = august.clientRef,
                amountText = "",
                currencyCode = "JPY",
                merchant = "",
                category = "住房",
                note = "自填备注",
                expenseTime = "2026-08-20T10:00:00Z",
            ),
        )
        assertEquals(august.clientRef, drafts.remembered(august.binding, august.seriesPublicId, "2026-08")?.clientRef)
        assertEquals(september.clientRef, drafts.remembered(september.binding, september.seriesPublicId, "2026-09")?.clientRef)
        assertEquals("", drafts.read(august.clientRef)?.amountText)
        val again = assertNotNull(
            recurringPaymentTask(
                loaded("JPY", 1200),
                september,
                remembered = drafts.remembered(august.binding, august.seriesPublicId, "2026-08"),
            ),
        )
        assertEquals(august.clientRef, again.clientRef)
        drafts.removeDraft(august.clientRef)
        assertNull(drafts.read(august.clientRef))
        assertEquals(august.clientRef, drafts.remembered(august.binding, august.seriesPublicId, "2026-08")?.clientRef)
        drafts.retireTask(august.clientRef)
        assertNull(drafts.remembered(august.binding, august.seriesPublicId, "2026-08"))
        assertEquals(september.clientRef, drafts.remembered(september.binding, september.seriesPublicId, "2026-09")?.clientRef)
    }

    @Test
    fun leftoverCompleteSessionStaysUntilOriginIsBound() {
        val json =
            """[{"binding":{"serverUrl":"https://occurrence.example","ledgerId":"ledger-1","ownerKey":"owner","sessionGeneration":"session","bindingRevision":"binding"},"seriesPublicId":"rec-1","period":"2026-08","clientRef":"legacy-ref","merchant":"日元订阅","obligationCurrencyCode":"JPY","plannedAmountCents":1200,"ledgerHomeCurrencyCode":"CNY","admitted":false}]"""
        val leftover = SavedStateHandle()
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] = json
        val store = RecurringPaymentDraftStore(SavedStateHandle())
        val parsed = assertNotNull(store.legacyPeriodPaymentSessions(leftover))
        assertEquals("legacy-ref", parsed.single().first.clientRef)
        assertEquals(json, leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY])
        assertNull(store.remembered(access.binding, "rec-1", "2026-08"))
    }

    @Test
    fun leftoverCapturedDraftFieldsRestoreWithoutInventingExpenseTime() {
        val json =
            """[{"binding":{"serverUrl":"https://occurrence.example","ledgerId":"ledger-1","ownerKey":"owner","sessionGeneration":"session","bindingRevision":"binding"},"seriesPublicId":"rec-1","period":"2026-08","clientRef":"legacy-ref","merchant":"日元订阅","obligationCurrencyCode":"JPY","plannedAmountCents":1200,"ledgerHomeCurrencyCode":"CNY","category":"住房","note":"自填备注","capturedAmountCents":9800,"admitted":false}]"""
        val leftover = SavedStateHandle()
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] = json
        val store = RecurringPaymentDraftStore(SavedStateHandle())
        val draft = assertNotNull(store.legacyPeriodPaymentSessions(leftover)?.single()?.second)
        assertEquals("9800", draft.amountText)
        assertEquals("JPY", draft.currencyCode)
        assertEquals("住房", draft.category)
        assertEquals("自填备注", draft.note)
        assertEquals("", draft.expenseTime)
        assertEquals(json, leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY])
        assertNull(store.read("legacy-ref"))
    }

    @Test
    fun leftoverIncompleteSessionKeepsTheLegacyKeyAndDoesNotRemember() {
        val json =
            """[{"binding":{"serverUrl":"https://occurrence.example","ledgerId":"ledger-1","ownerKey":"owner","sessionGeneration":"session","bindingRevision":"binding"},"seriesPublicId":"rec-1","period":"2026-08","clientRef":"legacy-ref","merchant":"日元订阅","obligationCurrencyCode":"JPY","plannedAmountCents":1200,"admitted":false}]"""
        val leftover = SavedStateHandle()
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] = json
        val store = RecurringPaymentDraftStore(SavedStateHandle())
        assertEquals(emptyList<Pair<RecurringPaymentTask, RecurringPaymentDraft?>>(), store.legacyPeriodPaymentSessions(leftover))
        assertEquals(json, leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY])
        assertNull(store.remembered(access.binding, "rec-1", "2026-08"))
        assertTrue(store.leftoverUnresolved(leftover, RecurringPaymentIdentity(access.binding, "rec-1", "2026-08")))
        assertTrue(!store.leftoverUnresolved(leftover, RecurringPaymentIdentity(access.binding, "rec-1", "2026-09")))
    }

    @Test
    fun leftoverMixedSessionsKeepOnlyTheIncompleteIdentity() {
        val json =
            """[{"binding":{"serverUrl":"https://occurrence.example","ledgerId":"ledger-1","ownerKey":"owner","sessionGeneration":"session","bindingRevision":"binding"},"seriesPublicId":"rec-1","period":"2026-08","clientRef":"complete-ref","merchant":"日元订阅","obligationCurrencyCode":"JPY","plannedAmountCents":1200,"ledgerHomeCurrencyCode":"CNY","admitted":false},{"binding":{"serverUrl":"https://occurrence.example","ledgerId":"ledger-1","ownerKey":"owner","sessionGeneration":"session","bindingRevision":"binding"},"seriesPublicId":"rec-1","period":"2026-09","clientRef":"incomplete-ref","merchant":"日元订阅","obligationCurrencyCode":"JPY","plannedAmountCents":1200,"admitted":false}]"""
        val leftover = SavedStateHandle()
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] = json
        val store = RecurringPaymentDraftStore(SavedStateHandle())
        val parsed = assertNotNull(store.legacyPeriodPaymentSessions(leftover))
        assertEquals("complete-ref", parsed.single().first.clientRef)
        assertEquals(json, leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY])
        assertTrue(store.leftoverUnresolved(leftover, RecurringPaymentIdentity(access.binding, "rec-1", "2026-08")))
        assertTrue(store.leftoverUnresolved(leftover, RecurringPaymentIdentity(access.binding, "rec-1", "2026-09")))
        assertTrue(!store.leftoverUnresolved(leftover, RecurringPaymentIdentity(access.binding, "rec-2", "2026-08")))
    }

    @Test
    fun leftoverUnparseableBlobBlocksEveryIdentity() {
        val leftover = SavedStateHandle()
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] = "not-json"
        val store = RecurringPaymentDraftStore(SavedStateHandle())
        assertNull(store.legacyPeriodPaymentSessions(leftover))
        assertTrue(store.leftoverUnresolved(leftover, RecurringPaymentIdentity(access.binding, "rec-1", "2026-08")))
        assertTrue(store.leftoverUnresolved(leftover, RecurringPaymentIdentity(access.binding, "rec-1", "2026-09")))
    }

    @Test
    fun rememberCanonicalClientRefDropsThePreviousDraft() {
        val store = RecurringPaymentDraftStore(SavedStateHandle())
        val stale = assertNotNull(recurringPaymentTask(loaded("JPY", 1200)))
        val origin = stale.copy(clientRef = "origin-a")
        store.remember(stale.copy(clientRef = "store-b"))
        store.write(
            RecurringPaymentDraft(
                clientRef = "store-b",
                amountText = "12",
                currencyCode = "JPY",
                merchant = "日元订阅",
                category = "住房",
                note = "旧草稿",
                expenseTime = "",
            ),
        )
        store.remember(origin)
        assertEquals("origin-a", store.remembered(origin.binding, origin.seriesPublicId, origin.period)?.clientRef)
        assertNull(store.read("store-b"))
        assertNull(store.read("origin-a"))
    }

    @Test
    fun aLaterOccurrenceGenerationDoesNotKeepThePreviousClientRef() {
        val first = assertNotNull(recurringPaymentTask(loaded("JPY", 1200)))
        assertEquals(3L, first.occurrenceRowVersion)
        val later = loaded("JPY", 1200).copy(
            occurrence = loaded("JPY", 1200).occurrence?.copy(rowVersion = 5L),
        )
        val again = assertNotNull(recurringPaymentTask(later, remembered = first))
        assertNotEquals(first.clientRef, again.clientRef)
        assertEquals(5L, again.occurrenceRowVersion)
        val sameGeneration = assertNotNull(recurringPaymentTask(loaded("JPY", 1200), remembered = first))
        assertEquals(first.clientRef, sameGeneration.clientRef)
        val leftover = first.copy(occurrenceRowVersion = null)
        val upgraded = assertNotNull(recurringPaymentTask(loaded("JPY", 1200), remembered = leftover))
        assertEquals(leftover.clientRef, upgraded.clientRef)
        assertEquals(3L, upgraded.occurrenceRowVersion)
    }

    private fun visible(
        resolved: Boolean = true,
        binding: LogicalSessionBinding? = access.binding,
        series: String? = "rec-1",
        period: String? = "2026-08",
        state: String? = "unfulfilled",
    ) = RecurringPaymentVisible(resolved, RecurringPaymentIdentity(binding, series, period), state)

    private fun loaded(currency: String?, planned: Long) = RecurringOccurrenceUiState(
        access = access,
        item = recurringItem { rowVersion = 7L }.copy(homeCurrencyCode = currency, merchant = "日元订阅"),
        occurrence = RecurringOccurrenceDto(
            seriesPublicId = "rec-1", period = "2026-08", seriesRowVersion = 7L, rowVersion = 3L,
            state = "unfulfilled", plannedAmountCents = planned, reservedAmountCents = planned,
            expensePublicId = null, paidAmountCents = null, nextDueDate = "2026-08-15", homeCurrencyCode = currency,
        ),
        requestedPeriod = "2026-08",
        ledgerHomeCurrencyCode = "CNY",
    )
}
