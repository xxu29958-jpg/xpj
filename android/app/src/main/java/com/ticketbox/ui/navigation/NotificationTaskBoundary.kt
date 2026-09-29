package com.ticketbox.ui.navigation

import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavBackStackEntry
import androidx.navigation.NavType
import androidx.navigation.navArgument
import com.squareup.moshi.Moshi
import com.squareup.moshi.Types
import com.ticketbox.R
import com.ticketbox.notification.NotificationTask
import com.ticketbox.notification.belongsTo
import com.ticketbox.notification.readNotificationTask
import com.ticketbox.notification.savedFields
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryScrollableColumn
import java.net.URLEncoder
import kotlinx.coroutines.flow.map

internal val LocalNotificationTask = staticCompositionLocalOf<NotificationTask?> { null }
internal const val NOTIFICATION_ARG = "notification"
internal const val NOTIFICATION_QUERY = "notification={notification}"
internal val notificationArgument get() = navArgument(NOTIFICATION_ARG) {
    type = NavType.StringType; nullable = true; defaultValue = null
}
private val taskFieldsAdapter = Moshi.Builder().build().adapter<List<String>>(
    Types.newParameterizedType(List::class.java, String::class.java))

internal fun notificationTaskRoute(route: String, task: NotificationTask): String =
    route + (if ('?' in route) "&" else "?") + "$NOTIFICATION_ARG=" +
        URLEncoder.encode(taskFieldsAdapter.toJson(task.savedFields()), "UTF-8")

/** The navigation entry retains the origin across process restoration and identity changes. */
@Composable
internal fun NotificationTaskBoundary(
    entry: NavBackStackEntry,
    factory: MainScreenFactory,
    onBack: () -> Unit,
    content: @Composable () -> Unit,
) {
    val raw = entry.arguments?.getString(NOTIFICATION_ARG)
    val task = remember(raw) { raw?.let { runCatching {
        taskFieldsAdapter.fromJson(it)?.let(::readNotificationTask)
    }.getOrNull() } }
    val binding by remember(factory) { factory.repository.observeLedgerAccess().map { it?.binding } }
        .collectAsStateWithLifecycle(factory.repository.captureDeferredLedgerBinding())
    // The calendar binding also exists for the server settings surface without an active ledger.
    val current = binding ?: factory.repositories.ledgerCalendarRepository?.currentBinding()
    if (raw != null && (task == null || !task.belongsTo(current))) {
        AppSecondaryScrollableColumn(chrome = AppSecondaryPageChrome(
            role = AppPageRole.Edit, title = stringResource(R.string.notification_original_task_title),
            subtitle = null, backText = stringResource(R.string.notification_original_task_back),
            onBack = onBack, hasBottomBar = false,
        )) { Text(stringResource(R.string.notification_original_binding_required)) }
    } else CompositionLocalProvider(LocalNotificationTask provides task, content = content)
}
