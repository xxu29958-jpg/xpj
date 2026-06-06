package com.ticketbox.viewmodel

import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.data.repository.TagActions
import com.ticketbox.domain.model.ManagedTag
import com.ticketbox.domain.model.TagMutationResult
import com.ticketbox.domain.model.TagUndoResult
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
        val repo = FakeTagActions(listOf(tag("a", "孤儿", 0), tag("b", "餐饮", 5)))
        val vm = TagManagementViewModel(repo)
        advanceUntilIdle()
        val names = vm.uiState.value.tags.map { it.name }
        assertEquals(listOf("餐饮", "孤儿"), names) // usage desc
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
        assertEquals(READ_ONLY_LEDGER_MESSAGE, vm.uiState.value.message)
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
        assertTrue(vm.uiState.value.message?.contains("合并") == true)
    }

    @Test
    fun stateConflictGetsTagFriendlyMessage() = runTest(dispatcher) {
        val repo = FakeTagActions(listOf(tag("a", "出差", 1)))
        val vm = TagManagementViewModel(repo)
        advanceUntilIdle()
        repo.failNext = RepositoryException("", "state_conflict")
        vm.deleteTag(tag("a", "出差", 1))
        advanceUntilIdle()
        assertTrue(vm.uiState.value.message?.contains("其它端") == true)
    }
}

/** Stateful fake: successful mutations mutate [tags] so the VM's reload reflects them. */
@OptIn(ExperimentalCoroutinesApi::class)
private class FakeTagActions(initial: List<ManagedTag>) : TagActions {
    private var tags = initial.toMutableList()
    var canModify = true
    var failNext: Throwable? = null
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
