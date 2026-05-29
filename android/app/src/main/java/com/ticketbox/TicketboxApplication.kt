package com.ticketbox

import android.app.Application

class TicketboxApplication : Application() {
    lateinit var container: AppContainer
        private set

    override fun onCreate() {
        super.onCreate()
        container = AppContainer(this)

        // ADR-0038 PR-2g.2: kick off the periodic outbox drain.
        // ``ensurePeriodic`` is idempotent (UPDATE policy on the
        // unique work name), so calling it on every cold start is
        // the right shape — it both seeds the schedule on a fresh
        // install and adopts the new schedule when an app upgrade
        // changes the interval / constraints.
        //
        // A kickoff one-time drain runs immediately too: the
        // periodic worker's first tick can be up to PERIODIC_INTERVAL
        // away on a fresh schedule, and any rows the user enqueued
        // during a previous offline session would otherwise sit
        // until then.
        container.outboxScheduler.ensurePeriodic(this)
        container.outboxScheduler.enqueueOnce(this)
    }
}
