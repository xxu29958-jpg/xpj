package com.ticketbox.data.repository

import java.io.InterruptedIOException
import java.net.SocketException
import java.net.UnknownHostException

/** Complete server query result, with the time and source of that particular read. */
data class ReadSnapshot<T>(val value: T, val fetchedAt: String, val fromCache: Boolean)

/** JSON, HTTP, TLS and local validation failures are not evidence of offline transport. */
internal fun Throwable?.isReadTransportUnavailable(): Boolean {
    val transport = (this as? RepositoryException)?.cause ?: this
    return transport is SocketException || transport is UnknownHostException || transport is InterruptedIOException
}
