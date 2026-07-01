package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.data.repository.RepositoryConflictDetails
import com.ticketbox.data.repository.TagActions
import com.ticketbox.data.repository.TagConflictDetails
import com.ticketbox.domain.model.ManagedTag
import com.ticketbox.domain.model.TagMutationResult
import com.ticketbox.domain.model.TagUndoResult
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class TagManagementViewModelTest {

    private val dispatcher = StandardTestDispatcher()

    @BeforeTest fun setup() { Dispatchers.setMain(dispatcher) }
    @AfterTest fun tearDown() { Dispatchers.resetMain() }

    private fun tag(id: String, name: String, usage: Int, rv: Long = 1L) =
        ManagedTag(publicId = id, name = name, usageCount = usage, rowVersion = rv)

    @Test
    fun initLoadsTagsSortedByUsageDesc() = runTest(dispatcher) {
        val repo = FakeTagActions(listOf(tag("a", "未使用", 0), tag("b", "餐饮", 5)))
        val vm = TagManagementViewModel(repo)
        advanceUntilIdle()
        val names = vm.uiState.value.tags.map { it.name }
        assertEquals(listOf("餐饮", "未使用"), names) // usage desc
    }

    @Test
    fun renameWithUnchangedNameDoesNotCallRepo() = runTest(dispatcher) {
        val repo = FakeTagActions(listOf(tag("a", "餐饮", 5)))
        val vm = TagManagementViewModel(repo)
        advanceUntilIdle()
        vm.renameTag(tag("a", "餐饮", 5), "餐饮")
        advanceUntilIdle()
        assertEquals(0, repo.renameCalls)
    }

    @Test
    fun renameBlockedForReadOnlyLedger() = runTest(dispatcher) {
        val repo = FakeTagActions(listOf(tag("a", "餐饮", 5))).apply { canModify = false }
        val vm = TagManagementViewModel(repo)
        advanceUntilIdle()
        vm.renameTag(tag("a", "餐饮", 5), "餐厅")
        advanceUntilIdle()
        assertEquals(0, repo.renameCalls)
        assertEquals(UiText.res(R.string.common_readonly_ledger), vm.uiState.value.message)
    }

    @Test
    fun deleteSetsUndoHandleWithSourceTokenAndDropsTag() = runTest(dispatcher) {
        val repo = FakeTagActions(listOf(tag("a", "出差", 3, rv = 2L), tag("b", "餐饮", 5)))
        val vm = TagManagementViewModel(repo)
        advanceUntilIdle()
        vm.deleteTag(tag("a", "出差", 3, rv = 2L))
        advanceUntilIdle()
        val state = vm.uiState.value
        val undo = state.undoable
        assertTrue(undo != null)
        assertEquals("mut-delete", undo.mutationPublicId)
        assertEquals(3L, undo.rowVersion) // source token = expected + 1
        assertEquals("出差", undo.label)
        assertTrue(state.tags.none { it.publicId == "a" }) // reloaded list drops it
    }

    @Test
    fun undoUsesHandleTokenAndClearsAffordance() = runTest(dispatcher) {
        val repo = FakeTagActions(listOf(tag("a", "出差", 3, rv = 2L)))
        val vm = TagManagementViewModel(repo)
        advanceUntilIdle()
        vm.deleteTag(tag("a", "出差", 3, rv = 2L))
        advanceUntilIdle()
        vm.undo()
        advanceUntilIdle()
        assertEquals(1, repo.undoCalls)
        assertEquals("mut-delete" to 3L, repo.lastUndo)
        assertNull(vm.uiState.value.undoable)
    }

    @Test
    fun undoWithoutHandleIsNoop() = runTest(dispatcher) {
        val repo = FakeTagActions(listOf(tag("a", "出差", 3)))
        val vm = TagManagementViewModel(repo)
        advanceUntilIdle()
        vm.undo()
        advanceUntilIdle()
        assertEquals(0, repo.undoCalls)
    }

    @Test
    fun undoWhileMutationInFlightIsIgnored() = runTest(dispatcher) {
        // ADR-0043 review (P3): a stale undo banner left from an earlier delete/merge
        // must not fire while a NEW mutation is in flight (the screen also disables
        // the button). undo() busy-gates and keeps the handle for after the op.
        val gate = CompletableDeferred<Unit>()
        val repo = FakeTagActions(listOf(tag("a", "出差", 3, rv = 2L)))
        val vm = TagManagementViewModel(repo)
        advanceUntilIdle()
        vm.deleteTag(tag("a", "出差", 3, rv = 2L))
        advanceUntilIdle() // delete done → undo banner armed, busy=false
        assertTrue(vm.uiState.value.undoable != null)

        repo.renameGate = gate
        vm.renameTag(tag("a", "出差", 3, rv = 2L), "差旅") // parks mid-flight, busy=true
        advanceUntilIdle()
        assertTrue(vm.uiState.value.busy)

        vm.undo() // must be ignored while busy
        advanceUntilIdle()
        assertEquals(0, repo.undoCalls)
        assertTrue(vm.uiState.value.undoable != null) // handle survived (not consumed)

        gate.complete(Unit)
        advanceUntilIdle()
    }

    @Test
    fun mergeSetsUndoHandleFromSourceAndDropsSource() = runTest(dispatcher) {
        val repo = FakeTagActions(listOf(tag("a", "出差", 1, rv = 4L), tag("b", "差旅", 2, rv = 6L)))
        val vm = TagManagementViewModel(repo)
        advanceUntilIdle()
        vm.mergeTags(tag("a", "出差", 1, rv = 4L), tag("b", "差旅", 2, rv = 6L))
        advanceUntilIdle()
        val undo = vm.uiState.value.undoable
        assertTrue(undo != null)
        assertEquals("mut-merge", undo.mutationPublicId)
        assertEquals(5L, undo.rowVersion) // source A token = 4 + 1
        assertTrue(vm.uiState.value.tags.none { it.publicId == "a" })
    }

    @Test
    fun renameConflictSurfacesMergeHint() = runTest(dispatcher) {
        val repo = FakeTagActions(listOf(tag("a", "出差", 1)))
        val vm = TagManagementViewModel(repo)
        advanceUntilIdle() // let the init load consume nothing; arm failure AFTER.
        repo.failNext = RepositoryException("标签名已被占用，请改用合并。", "tag_conflict")
        vm.renameTag(tag("a", "出差", 1), "差旅")
        advanceUntilIdle()
        // tag_conflict with no live target → failWith → toUiText maps the code to
        // R.string.error_tag_conflict ("标签名已被占用，请改用合并。"), byte-identical
        // to the prior resolved message.
        assertEquals(UiText.res(R.string.error_tag_conflict), vm.uiState.value.message)
        // The colliding key isn't a live tag in the list (e.g. soft-deleted) →
        // no merge prefill, just the steering message (契约 5 fallback).
        assertNull(vm.uiState.value.mergeSuggestion)
    }

    @Test
    fun renameConflictWithLiveTagPrefillsMerge() = runTest(dispatcher) {
        // 契约 5: renaming 出差 → 差旅 collides with the live 差旅 tag → the VM
        // steers into a preselected merge (source=出差, target=差旅), not silent.
        val repo = FakeTagActions(listOf(tag("a", "出差", 1), tag("b", "差旅", 2)))
        val vm = TagManagementViewModel(repo)
        advanceUntilIdle()
        repo.failNext = RepositoryException("标签名已被占用，请改用合并。", "tag_conflict")
        vm.renameTag(tag("a", "出差", 1), "差旅")
        advanceUntilIdle()
        val sug = vm.uiState.value.mergeSuggestion
        assertTrue(sug != null)
        assertEquals("a", sug.source.publicId)
        assertEquals("b", sug.target.publicId)
        // consume clears it (screen opened the dialog).
        vm.consumeMergeSuggestion()
        assertNull(vm.uiState.value.mergeSuggestion)
    }

    @Test
    fun renameConflictUsesFreshServerTokenForMergePrefill() = runTest(dispatcher) {
        // ADR-0043 review: when tag_conflict carries the colliding tag's fresh
        // public_id + row_version (details, 契约 5), the merge prefill must use that
        // FRESH token, not the stale local list entry — else the merge 409s at once.
        val repo = FakeTagActions(listOf(tag("a", "出差", 1), tag("b", "差旅", 2, rv = 3L)))
        val vm = TagManagementViewModel(repo)
        advanceUntilIdle()
        repo.failNext = RepositoryException(
            "标签名已被占用，请改用合并。",
            "tag_conflict",
            conflict = RepositoryConflictDetails(
                tag = TagConflictDetails(
                    publicId = "b",
                    rowVersion = 9L, // server is newer than the locally-loaded 3
                ),
            ),
        )
        vm.renameTag(tag("a", "出差", 1), "差旅")
        advanceUntilIdle()
        val sug = vm.uiState.value.mergeSuggestion
        assertTrue(sug != null)
        assertEquals("b", sug.target.publicId)
        assertEquals(9L, sug.target.rowVersion) // fresh server token, not the local 3
    }

    @Test
    fun mutationWhileBusyIsIgnored() = runTest(dispatcher) {
        // ADR-0043 review: rename/delete/merge early-return while a mutation is in
        // flight, so a double-tap can't fire a second request whose failure would
        // overwrite the winner's result.
        val gate = CompletableDeferred<Unit>()
        val repo = FakeTagActions(listOf(tag("a", "出差", 1))).apply { renameGate = gate }
        val vm = TagManagementViewModel(repo)
        advanceUntilIdle()
        vm.renameTag(tag("a", "出差", 1), "差旅")
        advanceUntilIdle() // first rename now parked mid-flight with busy=true
        assertTrue(vm.uiState.value.busy)
        vm.renameTag(tag("a", "出差", 1), "餐饮") // must be ignored (busy)
        advanceUntilIdle()
        assertEquals(1, repo.renameCalls)
        gate.complete(Unit)
        advanceUntilIdle()
    }

    @Test
    fun stateConflictGetsTagFriendlyMessage() = runTest(dispatcher) {
        val repo = FakeTagActions(listOf(tag("a", "出差", 1)))
        val vm = TagManagementViewModel(repo)
        advanceUntilIdle()
        repo.failNext = RepositoryException("", "state_conflict")
        vm.deleteTag(tag("a", "出差", 1))
        advanceUntilIdle()
        assertEquals(UiText.res(R.string.tag_management_error_state_conflict), vm.uiState.value.message)
    }

    // P4 stale-refresh: a committed tag mutation bumps tagsChangedRevision so the
    // screen tells the stats tab to re-pull its tag list (drop the dead chip).
    @Test
    fun successfulDeleteBumpsTagsChangedRevision() = runTest(dispatcher) {
        val repo = FakeTagActions(listOf(tag("a", "出差", 3, rv = 2L), tag("b", "餐饮", 5)))
        val vm = TagManagementViewModel(repo)
        advanceUntilIdle()
        assertEquals(0, vm.uiState.value.tagsChangedRevision)
        vm.deleteTag(tag("a", "出差", 3, rv = 2L))
        advanceUntilIdle()
        assertEquals(1, vm.uiState.value.tagsChangedRevision)
    }

    @Test
    fun failedMutationDoesNotBumpTagsChangedRevision() = runTest(dispatcher) {
        val repo = FakeTagActions(listOf(tag("a", "出差", 1)))
        val vm = TagManagementViewModel(repo)
        advanceUntilIdle()
        repo.failNext = RepositoryException("", "state_conflict")
        vm.deleteTag(tag("a", "出差", 1))
        advanceUntilIdle()
        // A failed mutation changed nothing on the server → stats must not be told to
        // refresh (otherwise the signal would fire on every failure too).
        assertEquals(0, vm.uiState.value.tagsChangedRevision)
    }

    @Test
    fun eachSuccessfulMutationBumpsRevisionMonotonically() = runTest(dispatcher) {
        val repo = FakeTagActions(
            listOf(tag("a", "出差", 3, rv = 2L), tag("b", "餐饮", 5), tag("c", "饭", 1)),
        )
        val vm = TagManagementViewModel(repo)
        advanceUntilIdle()
        vm.deleteTag(tag("a", "出差", 3, rv = 2L))
        advanceUntilIdle()
        vm.mergeTags(tag("c", "饭", 1), tag("b", "餐饮", 5))
        advanceUntilIdle()
        // Monotonic increment (not a set-to-1): two mutations → 2.
        assertEquals(2, vm.uiState.value.tagsChangedRevision)
    }

    // Pin the bump per committed path (not just delete/merge): rename and undo also
    // funnel through finishWithReload today, but a future split-out of either success
    // block could silently drop the stats-refresh signal with no failing test.
    @Test
    fun successfulRenameBumpsTagsChangedRevision() = runTest(dispatcher) {
        val repo = FakeTagActions(listOf(tag("a", "餐饮", 5)))
        val vm = TagManagementViewModel(repo)
        advanceUntilIdle()
        vm.renameTag(tag("a", "餐饮", 5), "餐厅")
        advanceUntilIdle()
        assertEquals(1, vm.uiState.value.tagsChangedRevision)
    }

    @Test
    fun successfulUndoBumpsTagsChangedRevision() = runTest(dispatcher) {
        val repo = FakeTagActions(listOf(tag("a", "出差", 3, rv = 2L), tag("b", "餐饮", 5)))
        val vm = TagManagementViewModel(repo)
        advanceUntilIdle()
        vm.deleteTag(tag("a", "出差", 3, rv = 2L))
        advanceUntilIdle()
        val beforeUndo = vm.uiState.value.tagsChangedRevision
        vm.undo()
        advanceUntilIdle()
        // Undo restored the tag → its own committed path must also bump (delta isolates
        // the undo contribution from the delete that set up the handle).
        assertEquals(beforeUndo + 1, vm.uiState.value.tagsChangedRevision)
    }
}

/** Stateful fake: successful mutations mutate [tags] so the VM's reload reflects them. */
@OptIn(ExperimentalCoroutinesApi::class)
private class FakeTagActions(initial: List<ManagedTag>) : TagActions {
    private var tags = initial.toMutableList()
    var canModify = true
    var failNext: Throwable? = null
    var renameGate: CompletableDeferred<Unit>? = null
    var renameCalls = 0
    var deleteCalls = 0
    var mergeCalls = 0
    var undoCalls = 0
    var lastUndo: Pair<String, Long>? = null

    private fun consumeFailure(): Throwable? = failNext?.also { failNext = null }

    override fun canModifyLedger(): Boolean = canModify

    override suspend fun tags(): Result<List<ManagedTag>> {
        consumeFailure()?.let { return Result.failure(it) }
        return Result.success(tags.toList())
    }

    override suspend fun renameTag(publicId: String, expectedRowVersion: Long, name: String): Result<Unit> {
        renameCalls++
        renameGate?.await()
        consumeFailure()?.let { return Result.failure(it) }
        tags = tags.map {
            if (it.publicId == publicId) it.copy(name = name.trim(), rowVersion = it.rowVersion + 1) else it
        }.toMutableList()
        return Result.success(Unit)
    }

    override suspend fun deleteTag(publicId: String, expectedRowVersion: Long): Result<TagMutationResult> {
        deleteCalls++
        consumeFailure()?.let { return Result.failure(it) }
        tags = tags.filterNot { it.publicId == publicId }.toMutableList()
        return Result.success(
            TagMutationResult("mut-delete", "delete", publicId, expectedRowVersion + 1, null, null, 1),
        )
    }

    override suspend fun mergeTags(
        sourcePublicId: String,
        sourceRowVersion: Long,
        targetPublicId: String,
        targetRowVersion: Long,
    ): Result<TagMutationResult> {
        mergeCalls++
        consumeFailure()?.let { return Result.failure(it) }
        tags = tags.filterNot { it.publicId == sourcePublicId }.toMutableList()
        return Result.success(
            TagMutationResult(
                "mut-merge", "merge", sourcePublicId, sourceRowVersion + 1,
                targetPublicId, targetRowVersion + 1, 2,
            ),
        )
    }

    override suspend fun undoTagMutation(mutationPublicId: String, expectedRowVersion: Long): Result<TagUndoResult> {
        undoCalls++
        lastUndo = mutationPublicId to expectedRowVersion
        consumeFailure()?.let { return Result.failure(it) }
        return Result.success(TagUndoResult("restored", expectedRowVersion + 1, 1, 0))
    }
}
