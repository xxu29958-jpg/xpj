package com.ticketbox.ui.screens

import androidx.compose.runtime.Composable

/**
 * Lets the same data-driven list render either as a secondary drill-in page or
 * as a view inside the primary obligations domain.
 */
data class RelationsListChrome(
    val title: String,
    val subtitle: String?,
    val backText: String,
    val onBack: (() -> Unit)?,
    val domainNavigation: (@Composable () -> Unit)? = null,
)
