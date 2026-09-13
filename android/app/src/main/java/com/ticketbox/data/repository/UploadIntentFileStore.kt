package com.ticketbox.data.repository

import android.content.Context
import android.util.AtomicFile
import com.ticketbox.upload.MAX_ORIGINAL_FALLBACK_BYTES
import com.ticketbox.upload.PreparedUploadImage
import java.io.DataInputStream
import java.io.File
import java.io.IOException
import java.io.RandomAccessFile
import java.nio.file.Files
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import okio.ByteString.Companion.toByteString

/** Original bytes only. Room owns acceptance, binding, ordering, delivery and deletion decisions. */
class UploadIntentFileStore internal constructor(
    context: Context,
    private val availableBytes: (File) -> Long,
) {
    constructor(context: Context) : this(context, { it.usableSpace })

    private val appContext = context.applicationContext

    /**
     * All readable slots must be durable before persist commits the one bound Room transaction.
     * Lock order is File -> Outbox lease. The callback must not reenter this store or delete files.
     * An exception, including an uncertain Room commit, leaves originals for reference-based recovery.
     */
    suspend fun <T : Any> acceptBatch(
        sources: List<UploadIntentFileSource>,
        beforePrepare: suspend () -> T?,
        persist: suspend (List<UploadIntentFileDescriptor?>) -> T,
    ): T {
        val batch = sources.toList()
        if (batch.size > MAX_UPLOAD_BATCH_ITEMS) throw UploadIntentFileException(UploadIntentFileFailure.BATCH_LIMIT)
        require(batch.map { it.key }.distinct().size == batch.size) { "Duplicate upload file key in batch" }
        return withFilesLocked { directory ->
            beforePrepare()?.let { return@withFilesLocked it }
            val files = batch.map { source ->
                currentCoroutineContext().ensureActive()
                prepareOriginal(directory, source)
            }
            currentCoroutineContext().ensureActive()
            persist(files)
        }
    }

    suspend fun read(descriptor: UploadIntentFileDescriptor): ByteArray {
        return withFilesLocked { directory -> readVerified(directory, descriptor) }
    }

    /** Null or an undecodable reference means that at least one original's ownership is unknown. */
    suspend fun collectOrphans(readAllReferencedKeys: suspend () -> Set<String>?): Int {
        return withFilesLocked { directory ->
            val referenced = readAllReferencedKeys() ?: return@withFilesLocked 0
            if (referenced.any { !isUploadIntentFileKey(it) }) return@withFilesLocked 0
            val files = directory.listFiles() ?: throw IOException("Cannot read upload staging directory")
            val orphanKeys = files.mapNotNull(::uploadFileKey).toSet() - referenced
            orphanKeys.forEach { deleteOriginal(directory, it) }
            orphanKeys.size
        }
    }

    private suspend fun <T> withFilesLocked(action: suspend (File) -> T): T {
        return withContext(Dispatchers.IO) {
            // A process-wide mutex also prevents overlapping FileChannel locks across store instances.
            processMutex.withLock {
                val directory = File(appContext.filesDir, DIRECTORY_NAME)
                if (Files.isSymbolicLink(directory.toPath())) throw IOException("Invalid upload staging directory")
                if (!directory.isDirectory && !directory.mkdirs()) throw IOException("Cannot create upload staging directory")
                val lockFile = File(directory, ".lock")
                requireUploadFile(lockFile)
                RandomAccessFile(lockFile, "rw").channel.use { channel ->
                    channel.lock().use {
                        currentCoroutineContext().ensureActive()
                        action(directory)
                    }
                }
            }
        }
    }

    private suspend fun prepareOriginal(
        directory: File,
        source: UploadIntentFileSource,
    ): UploadIntentFileDescriptor? {
        val existing = source.existing
        if (existing != null) {
            readVerified(directory, existing)
            return existing
        }
        val prepared = source.prepare() ?: return null
        require(prepared.bytes.size.toLong() in 1L..MAX_ORIGINAL_FALLBACK_BYTES) { "Invalid prepared upload size" }
        val descriptor = UploadIntentFileDescriptor(
            key = source.key,
            length = prepared.bytes.size.toLong(),
            sha256 = prepared.bytes.toByteString().sha256().hex(),
            metadata = UploadIntentFileMetadata(
                prepared.fileName, prepared.contentType, prepared.preparationDurationMs, prepared.sourceSizeBytes,
            ),
        )
        writeOriginal(directory, descriptor, prepared)
        return descriptor
    }

    private fun readVerified(directory: File, descriptor: UploadIntentFileDescriptor): ByteArray {
        if (descriptor.length > MAX_ORIGINAL_FALLBACK_BYTES) {
            throw UploadIntentFileException(UploadIntentFileFailure.CONTENT_MISMATCH)
        }
        val atomic = uploadAtomicFile(directory, descriptor.key)
        return atomic.openRead().use { input ->
            if (input.channel.size() != descriptor.length) {
                throw UploadIntentFileException(UploadIntentFileFailure.CONTENT_MISMATCH)
            }
            val bytes = ByteArray(descriptor.length.toInt())
            DataInputStream(input).readFully(bytes)
            if (input.read() != -1 || bytes.toByteString().sha256().hex() != descriptor.sha256) {
                throw UploadIntentFileException(UploadIntentFileFailure.CONTENT_MISMATCH)
            }
            bytes
        }
    }

    private fun writeOriginal(directory: File, descriptor: UploadIntentFileDescriptor, prepared: PreparedUploadImage) {
        val atomic = uploadAtomicFile(directory, descriptor.key)
        if (uploadFileParts(atomic.baseFile).any { it.exists() }) {
            readVerified(directory, descriptor)
            return
        }
        requireCapacity(directory, descriptor.length)
        val output = atomic.startWrite()
        try {
            output.write(prepared.bytes)
            atomic.finishWrite(output)
        } catch (error: Exception) {
            atomic.failWrite(output)
            throw error
        }
        // A failed finalization must never admit a Room reference to incomplete bytes.
        readVerified(directory, descriptor)
        if (availableBytes(directory) < MIN_FREE_BYTES) {
            throw UploadIntentFileException(UploadIntentFileFailure.DISK_RESERVE)
        }
    }

    private fun requireCapacity(directory: File, incomingBytes: Long) {
        var total = incomingBytes
        val files = directory.listFiles() ?: throw IOException("Cannot read upload staging directory")
        for (file in files) {
            requireUploadFile(file)
            val length = file.length()
            if (length > MAX_STAGING_BYTES - total) {
                throw UploadIntentFileException(UploadIntentFileFailure.STAGING_LIMIT)
            }
            total += length
        }
        if (availableBytes(directory) < MIN_FREE_BYTES + incomingBytes) {
            throw UploadIntentFileException(UploadIntentFileFailure.DISK_RESERVE)
        }
    }

    private fun deleteOriginal(directory: File, key: String) {
        val atomic = uploadAtomicFile(directory, key)
        for (file in uploadFileParts(atomic.baseFile)) {
            if (file.exists() && !file.delete()) throw IOException("Cannot release upload original")
        }
    }

    private companion object {
        val processMutex = Mutex()
        const val DIRECTORY_NAME = "upload-intents"
        const val MAX_STAGING_BYTES = 256L * 1024L * 1024L
        const val MIN_FREE_BYTES = 32L * 1024L * 1024L
    }
}

private fun requireUploadFile(file: File) {
    if (Files.isSymbolicLink(file.toPath()) || (file.exists() && !file.isFile)) {
        throw IOException("Invalid upload staging entry")
    }
}

private fun uploadFileParts(file: File): List<File> = listOf(file, File(file.path + ".bak"), File(file.path + ".new"))

private fun uploadAtomicFile(directory: File, key: String): AtomicFile {
    require(isUploadIntentFileKey(key)) { "Invalid upload file key" }
    val file = File(directory, "$key.upload")
    uploadFileParts(file).forEach(::requireUploadFile)
    return AtomicFile(file)
}

private fun uploadFileKey(file: File): String? {
    val name = when {
        file.name.endsWith(".upload.bak") || file.name.endsWith(".upload.new") -> file.name.dropLast(4)
        file.name.endsWith(".upload") -> file.name
        else -> return null
    }
    return name.removeSuffix(".upload").takeIf(::isUploadIntentFileKey)
}
