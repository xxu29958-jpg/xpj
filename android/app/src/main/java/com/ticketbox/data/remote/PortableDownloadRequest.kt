package com.ticketbox.data.remote

import java.util.concurrent.TimeUnit
import okhttp3.Call
import okhttp3.Interceptor

/** One user download owns cancellation and the deadline across network fallback calls. */
class PortableDownloadRequest {
    private val deadline = System.nanoTime() + TimeUnit.MINUTES.toNanos(5)
    private var cancelled = false
    private var activeCall: Call? = null

    @Synchronized fun attach(call: Call) {
        activeCall = call
        val remaining = deadline - System.nanoTime()
        if (cancelled || remaining <= 0) call.cancel()
        else call.timeout().timeout(remaining, TimeUnit.NANOSECONDS)
    }

    @Synchronized fun cancel() {
        cancelled = true
        activeCall?.cancel()
    }
}

internal fun portableDownloadInterceptor(): Interceptor = Interceptor { chain ->
    if (chain.request().tag(PortableDownloadRequest::class.java) == null) chain.proceed(chain.request())
    else chain.withReadTimeout(5, TimeUnit.MINUTES).proceed(chain.request())
}
