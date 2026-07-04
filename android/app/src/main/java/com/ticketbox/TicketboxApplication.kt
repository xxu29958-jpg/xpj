package com.ticketbox

import android.app.Application
import android.util.Log
import androidx.work.Configuration
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

class TicketboxApplication : Application(), Configuration.Provider {
    lateinit var container: AppContainer
        private set

    private val startupScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override val workManagerConfiguration: Configuration
        get() = Configuration.Builder().build()

    override fun onCreate() {
        super.onCreate()
        container = AppContainer(this)
        scheduleStartupWorkers()
    }

    private fun scheduleStartupWorkers() {
        startupScope.launch {
            scheduleStartupWork("outbox") {
                container.outboxScheduler.ensurePeriodic(this@TicketboxApplication)
                container.outboxScheduler.enqueueOnce(this@TicketboxApplication)
            }
            scheduleStartupWork("recurring reminder") {
                container.recurringReminderScheduler.ensurePeriodic(this@TicketboxApplication)
            }
            scheduleStartupWork("backup stale") {
                container.backupStaleScheduler.ensurePeriodic(this@TicketboxApplication)
            }
        }
    }

    private inline fun scheduleStartupWork(
        name: String,
        block: () -> Unit,
    ) {
        try {
            block()
        } catch (error: RuntimeException) {
            Log.w(TAG, "Startup work scheduling failed: $name", error)
        }
    }

    private companion object {
        const val TAG = "TicketboxApplication"
    }
}
