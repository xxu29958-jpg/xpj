package com.ticketbox

import android.app.Application
import android.util.Log
import androidx.work.Configuration
import com.ticketbox.security.isBusinessReady
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import java.util.concurrent.atomic.AtomicBoolean

class TicketboxApplication : Application(), Configuration.Provider {
    lateinit var container: AppContainer
        private set

    private val startupScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val startupWorkersScheduled = AtomicBoolean(false)

    override val workManagerConfiguration: Configuration
        get() = Configuration.Builder().build()

    override fun onCreate() {
        super.onCreate()
        container = AppContainer(this)
    }

    fun scheduleStartupWorkersAfterLaunchSettles() {
        if (!startupWorkersScheduled.compareAndSet(false, true)) return
        startupScope.launch {
            while (true) {
                container.sessionStore.observeSession().first { it.isBusinessReady() }
                delay(STARTUP_WORK_AFTER_LAUNCH_SETTLES_DELAY_MS)
                if (container.sessionStore.currentSession().isBusinessReady()) break
            }
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
        // Periodic maintenance can wait; mutation call sites still enqueue their
        // own immediate outbox drain, so this stays off the first-frame path.
        const val STARTUP_WORK_AFTER_LAUNCH_SETTLES_DELAY_MS = 20_000L
    }
}
