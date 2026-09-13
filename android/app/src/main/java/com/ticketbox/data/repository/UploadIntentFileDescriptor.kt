package com.ticketbox.data.repository

import com.squareup.moshi.JsonClass
import com.ticketbox.upload.PreparedUploadImage
import java.io.IOException
import java.util.UUID

/** Frozen wire preparation information, serialized directly in the original command payload. */
@JsonClass(generateAdapter = true)
data class UploadIntentFileMetadata(
    val fileName: String,
    val contentType: String?,
    val preparationDurationMs: Long,
    val sourceSizeBytes: Long,
)

/** A private file identity and integrity proof; it is not a filesystem path or an upload receipt. */
@JsonClass(generateAdapter = true)
data class UploadIntentFileDescriptor(
    val key: String,
    val length: Long,
    val sha256: String,
    val metadata: UploadIntentFileMetadata,
) {
    init {
        require(isUploadIntentFileKey(key)) { "Invalid upload file key" }
        require(length > 0L) { "Invalid upload file length" }
        require(sha256.matches(Regex("[0-9a-f]{64}"))) { "Invalid upload file fingerprint" }
    }
}

/**
 * An existing descriptor wins without preparing or opening the source URI again.
 * The caller reports an unreadable source and returns null for that slot; this store propagates
 * prepare exceptions so an uncertain preparation cannot silently consume the original action.
 */
data class UploadIntentFileSource(
    val key: String,
    val existing: UploadIntentFileDescriptor? = null,
    val prepare: suspend () -> PreparedUploadImage?,
) {
    init {
        require(isUploadIntentFileKey(key)) { "Invalid upload file key" }
        require(existing == null || existing.key == key) { "Upload file key does not match its original" }
    }
}

enum class UploadIntentFileFailure {
    BATCH_LIMIT,
    STAGING_LIMIT,
    DISK_RESERVE,
    CONTENT_MISMATCH,
}

class UploadIntentFileException(val failure: UploadIntentFileFailure) : IOException(failure.name)

internal fun isUploadIntentFileKey(key: String): Boolean =
    runCatching { UUID.fromString(key).toString() == key }.getOrDefault(false)
