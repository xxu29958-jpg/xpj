package com.ticketbox.ui.screens.settings

import androidx.annotation.StringRes
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.DiagnosticCheck
import com.ticketbox.domain.model.DiagnosticCheckKind
import com.ticketbox.domain.model.DiagnosticStatus

@Composable
internal fun diagnosticCheckName(check: DiagnosticCheck): String =
    stringResource(diagnosticCheckNameRes(check.kind))

@Composable
internal fun diagnosticCheckDetail(check: DiagnosticCheck): String = when (check.status) {
    DiagnosticStatus.Pass -> stringResource(diagnosticCheckPassDetailRes(check.kind))
    DiagnosticStatus.Warn -> stringResource(diagnosticCheckWarnDetailRes(check.kind))
    DiagnosticStatus.Fail -> check.detail?.takeIf { it.isNotBlank() } ?: stringResource(R.string.error_generic)
}

@StringRes
private fun diagnosticCheckNameRes(kind: DiagnosticCheckKind): Int = when (kind) {
    DiagnosticCheckKind.Auth -> R.string.settings_diagnostics_check_auth_name
    DiagnosticCheckKind.ServerSettings -> R.string.settings_diagnostics_check_server_name
    DiagnosticCheckKind.PendingExpenses -> R.string.settings_diagnostics_check_pending_name
    DiagnosticCheckKind.ConfirmedExpenses -> R.string.settings_diagnostics_check_confirmed_name
    DiagnosticCheckKind.MonthlyStats -> R.string.settings_diagnostics_check_stats_name
    DiagnosticCheckKind.CategoriesAndMonths -> R.string.settings_diagnostics_check_categories_name
    DiagnosticCheckKind.Duplicates -> R.string.settings_diagnostics_check_duplicates_name
    DiagnosticCheckKind.ProtectedImage -> R.string.settings_diagnostics_check_image_name
}

@StringRes
private fun diagnosticCheckPassDetailRes(kind: DiagnosticCheckKind): Int = when (kind) {
    DiagnosticCheckKind.Auth -> R.string.settings_diagnostics_check_auth_pass
    DiagnosticCheckKind.ServerSettings -> R.string.settings_diagnostics_check_server_pass
    DiagnosticCheckKind.PendingExpenses -> R.string.settings_diagnostics_check_pending_pass
    DiagnosticCheckKind.ConfirmedExpenses -> R.string.settings_diagnostics_check_confirmed_pass
    DiagnosticCheckKind.MonthlyStats -> R.string.settings_diagnostics_check_stats_pass
    DiagnosticCheckKind.CategoriesAndMonths -> R.string.settings_diagnostics_check_categories_pass
    DiagnosticCheckKind.Duplicates -> R.string.settings_diagnostics_check_duplicates_pass
    DiagnosticCheckKind.ProtectedImage -> R.string.settings_diagnostics_check_image_pass
}

@StringRes
private fun diagnosticCheckWarnDetailRes(kind: DiagnosticCheckKind): Int = when (kind) {
    DiagnosticCheckKind.ProtectedImage -> R.string.settings_diagnostics_check_image_skipped
    else -> R.string.settings_diagnostics_check_skipped
}
