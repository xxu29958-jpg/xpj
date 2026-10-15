package com.ticketbox.viewmodel

import com.ticketbox.domain.model.RuleApplicationBatch
import com.ticketbox.domain.model.RuleApplicationRollbackPreview
import com.ticketbox.domain.model.UiText

data class RuleRollbackState(
    val application: RuleApplicationBatch? = null,
    val visible: Boolean = false,
    val preview: RuleApplicationRollbackPreview? = null,
    val loading: Boolean = false,
    val reason: String = "",
    val submittedReason: String? = null,
    val error: UiText? = null,
)
