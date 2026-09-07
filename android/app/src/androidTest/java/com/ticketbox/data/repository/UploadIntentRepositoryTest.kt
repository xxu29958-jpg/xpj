package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.UploadResponseDto
import java.io.IOException
import java.util.TimeZone
import java.lang.reflect.Proxy
import java.time.Instant
import okhttp3.MultipartBody
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.Buffer
import retrofit2.HttpException
import retrofit2.Response
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class UploadIntentRepositoryTest {
    @Test
    fun anOriginalSelectionCannotBindToAnotherOriginOrAccountWithTheSameLedger() = runBlocking<Unit> {
        for (changeOrigin in listOf(true, false)) {
            UploadIntentRepositoryFixture().use { fixture ->
                var reads = 0
                val request = fixture.request(listOf("original.png")).copy(prepare = { reads++; fixture.image(it) })
                val original = fixture.session.value
                fixture.session.value = if (changeOrigin) original.copy(
                    serverUrl = "https://another.example.test", sessionGeneration = "new-session", bindingRevision = "new-binding",
                ) else original.copy(
                    identity = original.identity.copy(accountPublicId = "71000000-0000-4000-8000-000000000099"),
                    sessionGeneration = "new-session", bindingRevision = "new-binding",
                )

                assertTrue(fixture.repository.acceptUploadBatch(request).isFailure)
                assertEquals(request.expectedBinding.ledgerId, fixture.session.value.identity.ledgerId)
                assertEquals(0, reads)
                assertEquals(0, fixture.apiCalls)
                assertEquals(0, fixture.scheduled)
                assertTrue(fixture.dao.allRows().isEmpty())
            }
        }
    }

    @Test
    fun capacityRetryReadsTheSameDurableFileAndSendsTheSameOriginalKeyAndTimezone() = runBlocking<Unit> {
        UploadIntentRepositoryFixture().use { fixture ->
            val request = fixture.request(listOf("original.png"))
            val accepted = fixture.repository.acceptUploadBatch(request).getOrThrow()
            val original = fixture.dao.allRows().single()
            val attempts = mutableListOf<Triple<String, String?, String?>>()
            val unused = Proxy.newProxyInstance(ApiService::class.java.classLoader, arrayOf(ApiService::class.java)) {
                    _, method, _ -> error("Unexpected upload API: ${method.name}")
            } as ApiService
            val api = object : ApiService by unused {
                override suspend fun uploadScreenshot(
                    file: MultipartBody.Part, timezone: String?, idempotencyKey: String?,
                ): UploadResponseDto {
                    attempts += Triple(Buffer().also { file.body.writeTo(it) }.readUtf8(), timezone, idempotencyKey)
                    throw HttpException(Response.error<UploadResponseDto>(503,
                        """{"error":"enrichment_capacity_full","message":"Busy"}""".toResponseBody("application/json".toMediaType())))
                }
            }
            val engine = OutboxDrainEngine(fixture.outbox, listOf(UploadScreenshotDispatcher({ api },
                fixture.adapters.uploadPayloadAdapter, fixture.adapters.uploadReceiptAdapter, fixture.fileStore::read)),
                now = { Instant.parse(UploadIntentRepositoryFixture.NOW).toEpochMilli() })
            assertEquals(1, engine.drainOnce().failures)
            fixture.repository.recoverUploadGroup(request.expectedBinding, accepted.groupId, drop = false).getOrThrow()
            assertEquals(1, engine.drainOnce().failures)

            assertEquals(2, attempts.size)
            assertEquals(attempts[0], attempts[1])
            assertEquals("original.png", attempts[0].first)
            assertEquals(original.idempotencyKey, attempts[0].third)
            val retained = fixture.dao.allRows().single()
            assertEquals(PendingMutationStatus.Failed.wireValue, retained.status)
            assertTrue(retained.blocksFollowing)
            assertEquals(original.payload, retained.payload)
            assertEquals(original.idempotencyKey, retained.idempotencyKey)
            assertNull(retained.receiptJson)
            assertTrue(fixture.original(requireNotNull(original.idempotencyKey)).isFile)
        }
    }

    @Test
    fun acceptanceFreezesEverySlotAndNeverCreatesAReceipt() = runBlocking<Unit> {
        UploadIntentRepositoryFixture().use { fixture ->
            val reads = mutableListOf<String>()
            val request = fixture.request(listOf(" a/b.png ", "unreadable", "c.png")).copy(prepare = { name ->
                reads += name
                if (name == "unreadable") throw IOException("Source no longer readable")
                fixture.image(name).copy(contentType = " ")
            })
            val accepted = fixture.repository.acceptUploadBatch(request).getOrThrow()
            val rows = fixture.dao.allRows()
            assertEquals(request.imageRefs, reads)
            assertEquals(3, rows.size)
            assertEquals(rows.map { it.id }, accepted.rowIds)
            assertEquals(request.id, accepted.groupId)
            assertEquals(1, fixture.scheduled)
            assertEquals(0, fixture.apiCalls)
            assertTrue(fixture.savedTimestamps.isEmpty())
            val observation = fixture.repository.observeUploadIntents().first()
            assertTrue(observation.uploads.all { it.row.status == PendingMutationStatus.Pending && it.receipt == null })
            val payloads = observation.uploads.map { requireNotNull(it.payload) }
            assertEquals(listOf(0, 1, 2), payloads.map { it.batch.index })
            assertEquals((0..2).map { uploadItemKey(request.id, it) }, rows.map { it.idempotencyKey })
            assertTrue(payloads.all { it.origin == request.expectedBinding && it.batch.count == 3 })
            assertNull(payloads[1].file)
            assertEquals("a_b.png", requireNotNull(payloads[0].file).metadata.fileName)
            assertEquals("image/jpeg", requireNotNull(payloads[0].file).metadata.contentType)
            assertArrayEquals("c.png".toByteArray(), fixture.fileStore.read(requireNotNull(payloads[2].file)))
        }
    }

    @Test
    fun lostRoomAcknowledgementReopensTheSameKeysWithoutReadingSourcesOrChangingTimezone() = runBlocking<Unit> {
        UploadIntentRepositoryFixture().use { fixture ->
            val originalZone = TimeZone.getDefault()
            try {
                TimeZone.setDefault(TimeZone.getTimeZone("Asia/Shanghai"))
                val request = fixture.request()
                fixture.loseNextInsertAcknowledgement = true
                assertTrue(fixture.repository.acceptUploadBatch(request).isFailure)
                val original = fixture.dao.allRows()
                assertEquals(3, original.size)
                assertEquals(0, fixture.scheduled)
                TimeZone.setDefault(TimeZone.getTimeZone("America/Los_Angeles"))
                val reopened = fixture.reopen()
                val accepted = reopened.acceptUploadBatch(request.copy(prepare = {
                    error("An already accepted request must not reopen its URI")
                })).getOrThrow()
                assertEquals(original.map { it.id }, accepted.rowIds)
                assertEquals(original, fixture.dao.allRows())
                assertEquals("The recovered original pending rows need their missed enqueue wakeup", 1, fixture.scheduled)
                val recovered = reopened.observeUploadIntents().first()
                assertTrue(recovered.uploads.all { it.payload?.timezone == "Asia/Shanghai" })
                assertTrue(recovered.uploads.all { fixture.original(requireNotNull(it.row.idempotencyKey)).isFile })
                assertEquals(0, fixture.apiCalls)
            } finally {
                TimeZone.setDefault(originalZone)
            }
        }
    }

    @Test
    fun reopenedCapacityGroupKeepsReceiptAndOriginalTailAndAppendsWithoutRetry() = runBlocking<Unit> {
        UploadIntentRepositoryFixture().use { fixture ->
            val request = fixture.request()
            val accepted = fixture.repository.acceptUploadBatch(request).getOrThrow()
            fixture.outbox.markDone(accepted.rowIds[0], receiptJson = fixture.adapters.uploadReceiptAdapter.toJson(UploadIntentRepositoryFixture.RECEIPT))
            fixture.outbox.markFailed(accepted.rowIds[1], UPLOAD_CAPACITY_FULL)
            val original = fixture.dao.allRows()
            val reopened = fixture.reopen()
            fixture.failNextTimestampWrite = true
            val observation = withTimeout(5_000) { reopened.observeUploadIntents().first { it.uploads.size == 3 } }
            assertEquals(UploadIntentRepositoryFixture.RECEIPT, observation.uploads[0].receipt)
            assertEquals(original.map { it.payload }, observation.uploads.map { it.row.payloadJson })
            assertArrayEquals("b.png".toByteArray(), fixture.fileStore.read(requireNotNull(observation.uploads[1].payload?.file)))
            assertArrayEquals("c.png".toByteArray(), fixture.fileStore.read(requireNotNull(observation.uploads[2].payload?.file)))
            assertTrue(fixture.savedTimestamps.isEmpty())
            assertEquals(original, fixture.dao.allRows())
            reopened.observeUploadIntents().first()
            assertEquals(listOf("family" to UploadIntentRepositoryFixture.NOW), fixture.savedTimestamps)
            reopened.observeUploadIntents().first()
            assertEquals(1, fixture.savedTimestamps.size)
            val addition = fixture.request(listOf("d.png", "e.png"))
            assertEquals(accepted.groupId, reopened.acceptUploadBatch(addition).getOrThrow().groupId)
            assertEquals(original, fixture.dao.allRows().take(3))
            assertEquals(0, fixture.apiCalls)
            reopened.recoverUploadGroup(request.expectedBinding, accepted.groupId, drop = false).getOrThrow()
            val retried = fixture.dao.allRows()
            assertEquals("pending", retried[1].status)
            assertEquals(original[1].idempotencyKey, retried[1].idempotencyKey)
            assertEquals(original[1].payload, retried[1].payload)
            assertEquals(original[1].expectedRowVersion, retried[1].expectedRowVersion)
            assertEquals(original[0], retried[0])
            assertEquals(original[2], retried[2])
            for (row in retried) fixture.outbox.markDone(row.id,
                receiptJson = fixture.adapters.uploadReceiptAdapter.toJson(UploadIntentRepositoryFixture.RECEIPT))
            val next = fixture.request(listOf("f.png"))
            assertEquals(next.id, reopened.acceptUploadBatch(next).getOrThrow().groupId)
        }
    }

    @Test
    fun incompleteOriginalAcceptanceAndUnknownPayloadAreNotRecreatedOrCollected() = runBlocking<Unit> {
        UploadIntentRepositoryFixture().use { fixture ->
            val request = fixture.request()
            fixture.repository.acceptUploadBatch(request).getOrThrow()
            val originals = fixture.dao.allRows()
            fixture.dao.clearAll()
            fixture.dao.insert(originals[0])
            val future = originals[1].copy(type = "future_upload_owner", ownerKey = null)
            fixture.dao.insert(future)
            var reopens = 0
            assertTrue(fixture.repository.acceptUploadBatch(request.copy(prepare = {
                reopens++
                fixture.image(it)
            })).isFailure)
            assertEquals(0, reopens)
            assertEquals(listOf(originals[0], future), fixture.dao.allRows())
            assertEquals(0, fixture.repository.collectOrphans())
            assertTrue(fixture.original(requireNotNull(originals[2].idempotencyKey)).isFile)
            fixture.dao.clearAll()
            fixture.dao.insert(originals[0].copy(payload = "{\"revision\":999}", status = "failed",
                lastError = UPLOAD_UNSUPPORTED))
            assertNull(fixture.repository.observeUploadIntents().first().uploads.single().payload)
            val unsupported = fixture.dao.allRows()
            assertTrue(fixture.repository.recoverUploadGroup(request.expectedBinding, request.id, false).isFailure)
            assertEquals(unsupported, fixture.dao.allRows())
            assertEquals(0, fixture.repository.collectOrphans())
            assertTrue(fixture.original(requireNotNull(originals[2].idempotencyKey)).isFile)
            val decoded = requireNotNull(fixture.adapters.uploadPayloadAdapter.fromJson(originals[0].payload))
            val wrongOwner = decoded.copy(origin = decoded.origin.copy(ownerKey = "unproven-owner"))
            fixture.dao.clearAll()
            fixture.dao.insert(originals[0].copy(payload = fixture.adapters.uploadPayloadAdapter.toJson(wrongOwner)))
            assertEquals(0, fixture.repository.collectOrphans())
            assertTrue(fixture.original(requireNotNull(originals[2].idempotencyKey)).isFile)
        }
    }

    @Test
    fun refusalExpiryAndViewerRecoveryPreserveOriginalRowsAndFiles() = runBlocking<Unit> {
        UploadIntentRepositoryFixture().use { fixture ->
            val request = fixture.request(listOf("a.png", "b.png"))
            val accepted = fixture.repository.acceptUploadBatch(request).getOrThrow()
            fixture.outbox.markFailed(accepted.rowIds[0], "client_upgrade_required")
            fixture.outbox.markFailed(accepted.rowIds[1], "outbox_row_expired")
            val originals = fixture.dao.allRows()
            fixture.session.value = fixture.session.value.copy(identity = fixture.session.value.identity.copy(role = "viewer"))
            assertFalse(fixture.repository.observeUploadIntents().first().access?.canModify == true)
            assertTrue(fixture.repository.recoverUploadGroup(request.expectedBinding, accepted.groupId, false).isFailure)
            assertEquals(originals, fixture.dao.allRows())
            fixture.session.value = fixture.session.value.copy(identity = fixture.session.value.identity.copy(role = "member"))
            fixture.repository.recoverUploadGroup(request.expectedBinding, accepted.groupId, false).getOrThrow()
            val retried = fixture.dao.allRows()
            assertEquals("pending", retried[0].status)
            assertEquals(originals[0].payload, retried[0].payload)
            assertEquals(originals[0].idempotencyKey, retried[0].idempotencyKey)
            assertEquals(originals[1], retried[1])
            fixture.outbox.markFailed(retried[0].id, "idempotency_key_reused")
            val refused = fixture.dao.allRows()
            assertEquals(originals[0].payload, refused[0].payload)
            assertEquals(originals[0].idempotencyKey, refused[0].idempotencyKey)
            assertEquals("failed", refused[0].status)
            assertFalse(fixture.outbox.resolveFailed(refused[0].id, FailedResolution.Retry()))
            assertEquals(refused, fixture.dao.allRows())
            assertFalse(fixture.repository.observeUploadIntents().first().uploads.first().canRetry)
            assertTrue(fixture.repository.recoverUploadGroup(request.expectedBinding, accepted.groupId, false).isFailure)
            assertEquals(refused, fixture.dao.allRows())
            fixture.session.value = fixture.session.value.copy(bindingRevision = "another-binding")
            assertTrue(fixture.repository.recoverUploadGroup(request.expectedBinding, accepted.groupId, true).isFailure)
            assertEquals(refused, fixture.dao.allRows())
            assertTrue(refused.all { fixture.original(requireNotNull(it.idempotencyKey)).isFile })
        }
    }

    @Test
    fun cancelledPreparationAndAChangedBindingNeverAcceptAnUploadPrefix() = runBlocking<Unit> {
        UploadIntentRepositoryFixture().use { fixture ->
            val request = fixture.request()
            val cancellation = runCatching { fixture.repository.acceptUploadBatch(request.copy(prepare = { name ->
                if (name == "b.png") throw CancellationException("Preparation cancelled")
                fixture.image(name)
            })) }.exceptionOrNull()
            assertTrue(cancellation is CancellationException)
            assertTrue(fixture.dao.allRows().isEmpty())
            assertEquals(0, fixture.scheduled)
            val switched = fixture.repository.acceptUploadBatch(request.copy(prepare = { name ->
                fixture.session.value = fixture.session.value.copy(bindingRevision = "changed-during-prepare")
                fixture.image(name)
            }))
            assertTrue(switched.isFailure)
            assertTrue(fixture.dao.allRows().isEmpty())
            assertEquals(0, fixture.scheduled)
            assertTrue(fixture.original(uploadItemKey(request.id, 0)).isFile)
        }
    }

    @Test
    fun ordinaryFailureRemainsRecoverableWhileCapacityPausesAndUnreadableTailDoesNotBlock() = runBlocking<Unit> {
        UploadIntentRepositoryFixture().use { fixture ->
            val prepared = mutableListOf<String>()
            val request = fixture.request(listOf("a", "b", "unreadable", "d")).copy(prepare = { name ->
                prepared += name
                if (name == "unreadable") null else fixture.image(name)
            })
            val accepted = fixture.repository.acceptUploadBatch(request).getOrThrow()
            val original = fixture.dao.allRows()
            val attempts = mutableListOf<Triple<String, String?, String?>>()
            val api = originalUploadApi { file, timezone, key ->
                val name = Buffer().also { file.body.writeTo(it) }.readUtf8()
                attempts += Triple(name, timezone, key)
                val attempt = attempts.count { it.first == name }
                if (name == "a" && attempt == 1) throw IOException("Original acknowledgement unknown")
                if (name == "b" && attempt <= 2) throw HttpException(Response.error<UploadResponseDto>(503,
                    """{"error":"enrichment_capacity_full","message":"Busy"}""".toResponseBody("application/json".toMediaType())))
                UploadIntentRepositoryFixture.RECEIPT.copy(id = if (name == "a") 1 else if (name == "b") 2 else 4,
                    publicId = "expense-$name", enrichmentTaskPublicId = "task-$name")
            }
            val engine = OutboxDrainEngine(fixture.outbox, listOf(UploadScreenshotDispatcher({ api },
                fixture.adapters.uploadPayloadAdapter, fixture.adapters.uploadReceiptAdapter, fixture.fileStore::read)),
                now = { Instant.parse(UploadIntentRepositoryFixture.NOW).toEpochMilli() })

            assertEquals(2, engine.drainOnce().failures)
            assertEquals(listOf("a", "b"), attempts.map { it.first })
            assertEquals(listOf(false, true, true, true), fixture.dao.allRows().map { it.blocksFollowing })
            assertEquals(DrainSummary.IDLE, engine.drainOnce())
            fixture.repository.recoverUploadGroup(request.expectedBinding, accepted.groupId, false).getOrThrow()
            val repeatedCapacity = engine.drainOnce()
            assertEquals(1, repeatedCapacity.done)
            assertEquals(1, repeatedCapacity.failures)
            assertEquals(listOf("a", "b", "a", "b"), attempts.map { it.first })
            fixture.repository.recoverUploadGroup(request.expectedBinding, accepted.groupId, false).getOrThrow()
            val completedTail = engine.drainOnce()
            assertEquals(2, completedTail.done)
            assertEquals(1, completedTail.failures)

            assertEquals(listOf("a", "b", "a", "b", "b", "d"), attempts.map { it.first })
            assertEquals(request.imageRefs, prepared)
            for (sameOriginal in attempts.groupBy { it.first }.values) assertEquals(1, sameOriginal.distinct().size)
            val retained = fixture.repository.observeUploadIntents().first().uploads
            assertEquals(listOf("done", "done", "failed", "done"), retained.map { it.row.status.wireValue })
            assertEquals(original.map { it.payload }, retained.map { it.row.payloadJson })
            assertEquals(original.map { it.idempotencyKey }, retained.map { it.row.idempotencyKey })
            assertTrue(retained.filter { it.row.status == PendingMutationStatus.Done }.all { it.receipt != null })
            assertNull(retained[2].receipt)
            assertFalse(retained[2].canRetry)
            assertEquals(UPLOAD_UNREADABLE, retained[2].row.lastError)
            assertTrue(original.filterIndexed { index, _ -> index != 2 }
                .all { fixture.original(requireNotNull(it.idempotencyKey)).isFile })
        }
    }

    @Test
    fun theNextAcceptanceReclaimsAnUnacceptedPrefixWithoutDroppingAnotherBindingOriginal() = runBlocking<Unit> {
        UploadIntentRepositoryFixture().use { fixture ->
            val retained = fixture.request(listOf("retained.png"))
            fixture.repository.acceptUploadBatch(retained).getOrThrow()
            val original = fixture.dao.allRows().single()
            val interrupted = fixture.request(listOf("orphan.png", "cancel.png"))
            val error = runCatching { fixture.repository.acceptUploadBatch(interrupted.copy(prepare = { name ->
                if (name == "cancel.png") throw CancellationException("Preparation cancelled")
                fixture.image(name)
            })) }.exceptionOrNull()
            assertTrue(error is CancellationException)
            assertEquals(listOf(original), fixture.dao.allRows())
            val orphan = fixture.original(uploadItemKey(interrupted.id, 0))
            assertTrue(orphan.isFile)

            fixture.session.value = fixture.session.value.copy(identity = fixture.session.value.identity.copy(ledgerId = "other-ledger"))
            fixture.repository.acceptUploadBatch(fixture.request(listOf("new.png"))).getOrThrow()

            assertFalse(orphan.exists())
            assertEquals(original, fixture.dao.allRows().first())
            assertArrayEquals("retained.png".toByteArray(), fixture.original(requireNotNull(original.idempotencyKey)).readBytes())
            assertEquals(2, fixture.dao.allRows().size)
            assertEquals(0, fixture.apiCalls)
        }
    }
}

private fun originalUploadApi(send: (MultipartBody.Part, String?, String?) -> UploadResponseDto): ApiService {
    val unused = Proxy.newProxyInstance(ApiService::class.java.classLoader, arrayOf(ApiService::class.java)) {
            _, method, _ -> error("Unexpected upload API: ${method.name}")
    } as ApiService
    return object : ApiService by unused {
        override suspend fun uploadScreenshot(file: MultipartBody.Part, timezone: String?, idempotencyKey: String?) =
            send(file, timezone, idempotencyKey)
    }
}
