package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ticketbox.data.repository.LedgerRepository
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.ui.appearance.background.ImmersiveBackgroundScaffold
import com.ticketbox.ui.appearance.background.SurfaceRole
import com.ticketbox.ui.screens.settings.JoinFamilyLedgerScreen
import com.ticketbox.viewmodel.JoinFamilyLedgerViewModel
import com.ticketbox.viewmodel.joinFamilyLedgerViewModelFactory

/** Bound-device consumer for one invitation launched from Android's share sheet. */
internal data class InvitationLaunchActions(
    val onAccepted: () -> Unit,
    val onHandled: () -> Unit,
)

@Composable
internal fun InvitationLaunchHost(
    request: LaunchIntentRequest.JoinInvitation,
    ledgerRepository: LedgerRepository,
    actions: InvitationLaunchActions,
    backgroundSettings: BackgroundSettings,
    currentSkin: AppSkin,
) {
    ImmersiveBackgroundScaffold(
        backgroundSettings = backgroundSettings,
        currentSkin = currentSkin,
        surfaceRole = SurfaceRole.Settings,
    ) {
        val joinViewModel: JoinFamilyLedgerViewModel = viewModel(
            key = "join-family-ledger-launch",
            factory = joinFamilyLedgerViewModelFactory(ledgerRepository),
        )
        LaunchedEffect(request) { joinViewModel.consumeSharedInvitation(request.sharedText) }
        JoinFamilyLedgerScreen(
            viewModel = joinViewModel,
            onBack = actions.onHandled,
            onAccepted = actions.onAccepted,
            onInvitationConsumed = actions.onHandled,
        )
    }
}
