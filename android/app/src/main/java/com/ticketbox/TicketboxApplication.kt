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

        // ADR-0046 Slice 5: 注册固定支出提醒检测源的周期 worker。
        // ensurePeriodic 幂等（UPDATE policy + 唯一 work 名），冷启动每次调是对的——
        // 新装播种 schedule，app 升级改了 24h/6h interval 时换新。这里**不** enqueueOnce：
        // 固定支出是日级窗口（Contract 9），不需要冷启动立即扫一遍；周期 tick 足够，
        // 加速一次性触发留给 Slice 6 的前台同步钩子（本批不做）。
        container.recurringReminderScheduler.ensurePeriodic(this)

        // 轴 6 备份超龄提醒：同形态注册 24h 周期 worker（0046 边界契约，日级
        // sent-key 去重在 engine 纯层）。stale 阈值 48h 在服务端单源，无需加速触发。
        container.backupStaleScheduler.ensurePeriodic(this)
    }
}
