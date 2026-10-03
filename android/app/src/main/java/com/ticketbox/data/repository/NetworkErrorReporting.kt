package com.ticketbox.data.repository

import android.util.Log
import com.ticketbox.BuildConfig
import java.time.Instant
import java.util.Collections
import java.util.IdentityHashMap

private val bearerPattern = Regex("(?i)\\bBearer\\s+[A-Za-z0-9._~+/=-]+")
private val secretPattern = Regex(
    "(?i)((?:authorization|cookie|set-cookie|upload[-_]token|upload[-_]key|pairing[-_ ]?code|" +
        "pairing|invitation|bootstrap[-_]secret|access[-_]token|refresh[-_]token|session[-_]token|" +
        "api[-_]key|token|password|secret)[\"']?\\s*[:=]\\s*[\"']?)([^\\s,;\"'&<>]+)",
)

internal fun safeRequestId(value: String?): String? = value?.takeIf { it.length in 1..64 && it.none(Char::isISOControl) }

private fun sanitizedDiagnosticText(message: String): String = message
    .replace(bearerPattern, "Bearer ***")
    .replace(secretPattern) { "${it.groupValues[1]}***" }
    .replace(Regex("/u/[A-Za-z0-9_-]+"), "/u/***")
    .replace(Regex("(https?://)[^\\s/@]+@"), "$1***@")
    .replace(Regex("(?i)\\b[A-Z]:[\\\\/][^\\s\"'<>]+"), "[local-path]")
    .replace('\n', ' ').replace('\r', ' ')

private fun projectFrames(frames: Array<StackTraceElement>): String = frames
    .filter { it.className.startsWith("com.ticketbox.") }
    .take(16)
    .joinToString("\n") { "  at ${it.className}.${it.methodName}(${it.fileName}:${it.lineNumber})" }

/** Existing Logcat output, in all build types. Never hand a raw throwable/message to Log.w. */
internal fun logNetworkWarning(message: String, error: Throwable? = null) {
    try {
        val output = buildString {
            append("${Instant.now()} Android version=${BuildConfig.VERSION_NAME} ")
            append("variant=${BuildConfig.FLAVOR}/${BuildConfig.BUILD_TYPE} ")
            append("source_tree_sha256=${BuildConfig.SOURCE_FINGERPRINT} ")
            append(sanitizedDiagnosticText(message))
            val seen = Collections.newSetFromMap(IdentityHashMap<Throwable, Boolean>())
            var current = error
            while (current != null && seen.size < 8 && seen.add(current)) {
                append("\n${current.javaClass.simpleName}\n${projectFrames(current.stackTrace)}")
                current = current.cause
            }
            append("\nreported_at:\n${projectFrames(Throwable().stackTrace)}")
        }
        Log.w("TicketboxNetwork", output)
    } catch (_: Exception) {
        // A sink fault or plain-JVM Android stub must not change Result/cause or retry business work.
    }
}
