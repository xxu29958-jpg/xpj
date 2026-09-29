package com.ticketbox.ui.navigation

import androidx.navigation.NavHostController
import com.ticketbox.notification.NotificationDestination
import com.ticketbox.notification.NotificationTask

/** Existing task owners still perform their reads and permission checks after navigation. */
internal fun openNotificationTask(task: NotificationTask, shell: MainShellState, nav: NavHostController) {
    val target = task.destination
    if (target is NotificationDestination.Expense) {
        nav.navigate(notificationTaskRoute(expenseRoute(target.id), task))
        return
    }
    nav.navigate(MAIN_ROUTE) { launchSingleTop = true }
    when (target) {
        is NotificationDestination.Repayment -> shell.openSecondaryPage(ProductSecondaryPage.RepaymentDrafts,
            notificationTaskRoute(repaymentDraftRoute(target.publicId), task), singleTop = false)
        is NotificationDestination.Recurring -> shell.openSecondaryPage(ProductSecondaryPage.Recurring,
            notificationTaskRoute(ProductSecondaryPage.Recurring.route, task), singleTop = false)
        is NotificationDestination.Budget -> shell.openSecondaryPage(ProductSecondaryPage.Budget, notificationTaskRoute(budgetRoute(target.month), task), singleTop = false)
        NotificationDestination.Backup -> shell.openAccount(notificationTaskRoute(WORKSPACE_ROUTE, task))
        is NotificationDestination.Expense -> Unit
    }
}
