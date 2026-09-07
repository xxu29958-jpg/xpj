package com.ticketbox.data.repository

import android.content.Context
import android.content.ContextWrapper
import androidx.test.platform.app.InstrumentationRegistry
import com.squareup.moshi.Moshi
import com.ticketbox.upload.PreparedUploadImage
import java.io.Closeable
import java.io.File
import java.io.IOException
import java.io.RandomAccessFile
import java.nio.channels.OverlappingFileLockException
import java.nio.file.Files
import java.util.UUID
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

/** Real Android files and AtomicFile; only the available-space number has a test seam. */
class UploadIntentFileStoreTest {
    @Test
    fun batchFreezesOriginalBytesMetadataAndUnreadablePositionsBeforeCommit() = runBlocking<Unit> {
        UploadFileFixture().use { fixture ->
            val store = UploadIntentFileStore(fixture.context)
            val firstKey = UUID.randomUUID().toString()
            val secondKey = UUID.randomUUID().toString()
            val prepared = fixture.image()
            val events = mutableListOf<String>()
            val sources = listOf(
                UploadIntentFileSource(firstKey) { events += "first"; prepared },
                UploadIntentFileSource(UUID.randomUUID().toString()) { events += "unreadable"; null },
                UploadIntentFileSource(secondKey) { events += "second"; prepared },
            )

            val descriptors = store.acceptBatch(beforePrepare = { null }, sources = sources) { files ->
                assertEquals(listOf("first", "unreadable", "second"), events)
                assertArrayEquals(prepared.bytes, fixture.original(firstKey).readBytes())
                assertArrayEquals(prepared.bytes, fixture.original(secondKey).readBytes())
                events += "commit"
                files
            }

            assertNull(descriptors[1])
            val first = requireNotNull(descriptors[0])
            val second = requireNotNull(descriptors[2])
            assertEquals(listOf(firstKey, null, secondKey), descriptors.map { it?.key })
            assertEquals(UploadIntentFileMetadata("original.png", "image/png", 17L, 123L), first.metadata)
            assertEquals(first.sha256, second.sha256)
            val adapter = Moshi.Builder().build().adapter(UploadIntentFileDescriptor::class.java).serializeNulls()
            assertEquals(first, adapter.fromJson(adapter.toJson(first)))
            val reopened = UploadIntentFileStore(fixture.context)
            val reused = reopened.acceptBatch(beforePrepare = { null }, sources = listOf(UploadIntentFileSource(firstKey, first) {
                error("A durable original must not reopen its URI")
            })) { requireNotNull(it.single()) }
            assertEquals(first, reused)
            assertArrayEquals(prepared.bytes, reopened.read(first))
            assertEquals(listOf("first", "unreadable", "second", "commit"), events)
        }
    }

    @Test
    fun reusedKeyCannotReplaceBytesAndInvalidReadDoesNotDeleteOriginal() = runBlocking<Unit> {
        UploadFileFixture().use { fixture ->
            val store = UploadIntentFileStore(fixture.context)
            val original = fixture.save(store)
            val originalBytes = store.read(original)

            val collision = runCatching {
                store.acceptBatch(beforePrepare = { null }, sources = listOf(UploadIntentFileSource(original.key) {
                    fixture.image().copy(bytes = byteArrayOf(9, 8, 7))
                })) { error("Different bytes cannot reach Room") }
            }.exceptionOrNull()
            assertEquals(UploadIntentFileFailure.CONTENT_MISMATCH, (collision as UploadIntentFileException).failure)
            val wrongLength = runCatching { store.read(original.copy(length = original.length + 1)) }.exceptionOrNull()
            val wrongHash = runCatching { store.read(original.copy(sha256 = "0".repeat(64))) }.exceptionOrNull()
            assertEquals(UploadIntentFileFailure.CONTENT_MISMATCH, (wrongLength as UploadIntentFileException).failure)
            assertEquals(UploadIntentFileFailure.CONTENT_MISMATCH, (wrongHash as UploadIntentFileException).failure)
            assertArrayEquals(originalBytes, store.read(original))
            assertThrows(IllegalArgumentException::class.java) {
                UploadIntentFileSource("../outside") { fixture.image() }
            }
        }
    }

    @Test
    fun batchLimitRefusesTheWholeSelectionBeforePreparation() = runBlocking<Unit> {
        UploadFileFixture().use { fixture ->
            var prepared = 0
            var committed = false
            val sources = List(101) {
                UploadIntentFileSource(UUID.randomUUID().toString()) { prepared++; fixture.image() }
            }
            val failure = runCatching {
                UploadIntentFileStore(fixture.context).acceptBatch(beforePrepare = { null }, sources = sources) { committed = true }
            }.exceptionOrNull()

            assertEquals(UploadIntentFileFailure.BATCH_LIMIT, (failure as UploadIntentFileException).failure)
            assertEquals(0, prepared)
            assertFalse(committed)
        }
    }

    @Test
    fun stagingLimitCountsUnclaimedFilesAndNeverCommitsOnlyThePrefix() = runBlocking<Unit> {
        UploadFileFixture().use { fixture ->
            val store = UploadIntentFileStore(fixture.context)
            store.collectOrphans { null } // Create the real locked staging directory.
            withContext(Dispatchers.IO) {
                // Sparse length exercises aggregate accounting without filling the emulator disk.
                RandomAccessFile(File(fixture.staging, "unproven-original"), "rw").use {
                    it.setLength(256L * 1024L * 1024L - 3L)
                }
            }
            val firstKey = UUID.randomUUID().toString()
            var committed = false
            val sources = listOf(firstKey, UUID.randomUUID().toString()).map { key ->
                UploadIntentFileSource(key) { fixture.image().copy(bytes = byteArrayOf(1, 2)) }
            }
            val failure = runCatching { store.acceptBatch(beforePrepare = { null }, sources = sources) { committed = true } }.exceptionOrNull()

            assertEquals(UploadIntentFileFailure.STAGING_LIMIT, (failure as UploadIntentFileException).failure)
            assertFalse(committed)
            assertTrue(fixture.original(firstKey).exists())
            assertTrue(File(fixture.staging, "unproven-original").exists())
        }
    }

    @Test
    fun diskReserveRefusesNewBytesButAllowsExistingOriginalAndExactBoundary() = runBlocking<Unit> {
        UploadFileFixture().use { fixture ->
            val reserve = 32L * 1024L * 1024L
            val prepared = fixture.image()
            var available = reserve + prepared.bytes.size
            val store = UploadIntentFileStore(fixture.context) { available }
            val original = fixture.save(store)
            available--
            val failure = runCatching { fixture.save(store) }.exceptionOrNull()
            assertEquals(UploadIntentFileFailure.DISK_RESERVE, (failure as UploadIntentFileException).failure)

            available = 0L
            val reused = store.acceptBatch(beforePrepare = { null }, sources = listOf(UploadIntentFileSource(original.key, original) {
                error("Existing bytes need neither source nor new disk reservation")
            })) { requireNotNull(it.single()) }
            assertEquals(original, reused)
            assertArrayEquals(prepared.bytes, store.read(original))

            var spaceReads = 0
            val allocatedStore = UploadIntentFileStore(fixture.context) {
                if (spaceReads++ == 0) reserve + prepared.bytes.size else reserve - 1L
            }
            val newKey = UUID.randomUUID().toString()
            var committed = false
            val allocationFailure = runCatching {
                allocatedStore.acceptBatch(beforePrepare = { null }, sources = listOf(UploadIntentFileSource(newKey) { prepared })) { committed = true }
            }.exceptionOrNull()
            assertEquals(UploadIntentFileFailure.DISK_RESERVE, (allocationFailure as UploadIntentFileException).failure)
            assertFalse(committed)
            assertTrue(fixture.original(newKey).exists())
        }
    }

    @Test
    fun uncertainCommitPreservesFilesAndOnlyCompleteReferencesPermitOrphanDeletion() = runBlocking<Unit> {
        UploadFileFixture().use { fixture ->
            val store = UploadIntentFileStore(fixture.context)
            var staged: UploadIntentFileDescriptor? = null
            val commitFailure = IOException("Unknown Room commit result")
            val observed = runCatching {
                store.acceptBatch(beforePrepare = { null }, sources = listOf(UploadIntentFileSource(UUID.randomUUID().toString()) { fixture.image() })) {
                    staged = it.single()
                    throw commitFailure
                }
            }.exceptionOrNull()
            assertTrue(observed === commitFailure)
            val original = requireNotNull(staged)
            assertArrayEquals(fixture.image().bytes, store.read(original))
            val another = fixture.save(store)
            assertEquals(0, store.collectOrphans { null })
            assertEquals(0, store.collectOrphans { setOf("unknown-payload-reference") })
            assertEquals(1, store.collectOrphans { setOf(original.key) })
            assertArrayEquals(fixture.image().bytes, store.read(original))
            assertFalse(fixture.original(another.key).exists())
            store.releaseAfterRowDeletion(setOf(original.key))
            assertFalse(fixture.original(original.key).exists())
        }
    }

    @Test
    fun atomicBackupIsRecoveredBeforeValidatingTheFrozenOriginal() = runBlocking<Unit> {
        UploadFileFixture().use { fixture ->
            val store = UploadIntentFileStore(fixture.context)
            val original = fixture.save(store)
            withContext(Dispatchers.IO) {
                val file = fixture.original(original.key)
                assertTrue(file.renameTo(File(file.path + ".bak")))
                file.writeBytes(byteArrayOf(9))
            }

            assertArrayEquals(fixture.image().bytes, store.read(original))
            assertArrayEquals(fixture.image().bytes, store.read(original))
        }
    }

    @Test
    fun concurrentReentryUsesTheAcceptedOriginalWithoutReopeningItsSource() = runBlocking<Unit> {
        UploadFileFixture().use { fixture ->
            val first = UploadIntentFileStore(fixture.context)
            val reopened = UploadIntentFileStore(fixture.context)
            val key = UUID.randomUUID().toString()
            val enteredCommit = CompletableDeferred<Unit>()
            val releaseCommit = CompletableDeferred<Unit>()
            var accepted: List<Long>? = null
            var sourceReads = 0
            val accepting = async(Dispatchers.Default) {
                first.acceptBatch(
                    sources = listOf(UploadIntentFileSource(key) { sourceReads++; fixture.image() }),
                    beforePrepare = { accepted },
                ) {
                    enteredCommit.complete(Unit)
                    releaseCommit.await()
                    listOf(17L).also { accepted = it }
                }
            }
            enteredCommit.await()
            val reentering = async(Dispatchers.IO, start = CoroutineStart.UNDISPATCHED) {
                reopened.acceptBatch(
                    sources = listOf(UploadIntentFileSource(key) { error("The original URI has been revoked") }),
                    beforePrepare = { accepted },
                ) { error("A committed original cannot be accepted again") }
            }
            try {
                assertFalse(reentering.isCompleted)
            } finally {
                releaseCommit.complete(Unit)
            }
            assertEquals(listOf(17L), accepting.await())
            assertEquals(listOf(17L), reentering.await())
            assertEquals(1, sourceReads)
            assertArrayEquals(fixture.image().bytes, fixture.original(key).readBytes())
        }
    }

    @Test
    fun twoInstancesSerializeAcceptanceAndReferenceReadsAcrossTheRoomCommit() = runBlocking<Unit> {
        UploadFileFixture().use { fixture ->
            val first = UploadIntentFileStore(fixture.context)
            val second = UploadIntentFileStore(fixture.context)
            val enteredCommit = CompletableDeferred<UploadIntentFileDescriptor>()
            val releaseCommit = CompletableDeferred<Unit>()
            val referencesRead = CompletableDeferred<Unit>()
            val accepting = async(Dispatchers.Default) {
                first.acceptBatch(beforePrepare = { null }, sources = listOf(UploadIntentFileSource(UUID.randomUUID().toString()) { fixture.image() })) {
                    val descriptor = requireNotNull(it.single())
                    RandomAccessFile(File(fixture.staging, ".lock"), "rw").channel.use { channel ->
                        assertThrows(OverlappingFileLockException::class.java) { channel.tryLock()?.release() }
                    }
                    enteredCommit.complete(descriptor)
                    releaseCommit.await()
                    descriptor
                }
            }
            val original = enteredCommit.await()
            val collecting = async(Dispatchers.IO, start = CoroutineStart.UNDISPATCHED) {
                second.collectOrphans {
                    referencesRead.complete(Unit)
                    setOf(original.key)
                }
            }
            try {
                assertFalse(referencesRead.isCompleted)
                assertFalse(collecting.isCompleted)
            } finally {
                releaseCommit.complete(Unit)
            }
            assertEquals(original, accepting.await())
            assertEquals(0, collecting.await())
            assertTrue(referencesRead.isCompleted)
            assertArrayEquals(fixture.image().bytes, second.read(original))
        }
    }
}

/** Its entire directory is unique test storage, never the application's real upload root. */
private class UploadFileFixture : Closeable {
    private val base = InstrumentationRegistry.getInstrumentation().targetContext
    private val directory = Files.createTempDirectory(base.cacheDir.toPath(), "upload-file-test-").toFile()
    val context = object : ContextWrapper(base) {
        override fun getApplicationContext(): Context = this
        override fun getFilesDir(): File = directory
    }
    val staging = File(directory, "upload-intents")

    fun original(key: String): File = File(staging, "$key.upload")

    fun image(): PreparedUploadImage = PreparedUploadImage(
        fileName = "original.png",
        contentType = "image/png",
        bytes = byteArrayOf(1, 2, 3),
        sourceSizeBytes = 123L,
        preparationDurationMs = 17L,
    )

    suspend fun save(store: UploadIntentFileStore): UploadIntentFileDescriptor = store.acceptBatch(beforePrepare = { null }, sources =
        listOf(UploadIntentFileSource(UUID.randomUUID().toString()) { image() }),
    ) { requireNotNull(it.single()) }

    override fun close() {
        check(directory.parentFile.canonicalFile == base.cacheDir.canonicalFile)
        check(directory.name.startsWith("upload-file-test-"))
        check(directory.deleteRecursively())
    }
}
