package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.LocalRepositoryFailure
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.UiText
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class LocalRepositoryFailureUiTextTest {
    @Test fun localValidationHasSpecificRecoveryCopyWithoutClaimingABackendCode() {
        val copy = mapOf(LocalRepositoryFailure.ManualRateReviewRequired to R.string.advice_rate_submission_review,
            LocalRepositoryFailure.ManualRateUnresolved to R.string.advice_rate_unresolved,
            LocalRepositoryFailure.ManualRateChanged to R.string.advice_rate_changed,
            LocalRepositoryFailure.BudgetInputsUnverified to R.string.advice_inputs_load_failed)
        copy.forEach { (reason, resource) ->
            val error = RepositoryException(reason.name, localFailure = reason)
            assertNull(error.errorCode)
            assertEquals(UiText.res(resource), error.toUiText())
        }
    }
}
