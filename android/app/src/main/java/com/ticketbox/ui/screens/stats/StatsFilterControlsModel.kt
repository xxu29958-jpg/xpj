package com.ticketbox.ui.screens.stats

import com.ticketbox.ui.components.buildAppTagFilterChoices
import com.ticketbox.viewmodel.StatsFilterOptionsLoadState
import com.ticketbox.viewmodel.StatsUiState

internal enum class StatsTagFilterControlKind { Hidden, Loading, Failed, Menu }

internal data class StatsTagFilterControlModel(
    val kind: StatsTagFilterControlKind,
    val choices: List<String> = emptyList(),
)

internal fun statsTagFilterControlModel(
    state: StatsUiState,
    optionLimit: Int,
): StatsTagFilterControlModel {
    val choices = buildAppTagFilterChoices(
        availableTags = state.tags + state.stats?.byTag.orEmpty().map { it.tag },
        selectedTag = state.selectedTag,
        limit = optionLimit,
    )
    return when {
        choices.isNotEmpty() -> StatsTagFilterControlModel(
            kind = StatsTagFilterControlKind.Menu,
            choices = choices,
        )
        state.tagsLoadState == StatsFilterOptionsLoadState.Loading -> StatsTagFilterControlModel(
            kind = StatsTagFilterControlKind.Loading,
        )
        state.tagsLoadState == StatsFilterOptionsLoadState.Failed -> StatsTagFilterControlModel(
            kind = StatsTagFilterControlKind.Failed,
        )
        else -> StatsTagFilterControlModel(kind = StatsTagFilterControlKind.Hidden)
    }
}
