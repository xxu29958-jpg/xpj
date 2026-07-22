package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.CategoryPreferenceActions
import com.ticketbox.domain.model.CategoryPreference
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
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

@OptIn(ExperimentalCoroutinesApi::class)
class CategoryDirectoryViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @BeforeTest
    fun setUp() {
        Dispatchers.setMain(dispatcher)
    }

    @AfterTest
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun initialLoadSortsByUsageThenName() = runTest(dispatcher) {
        val repository = FakeCategoryPreferenceActions(
            items = mutableListOf(
                category("travel", "差旅", usage = 2),
                category("coffee", "咖啡", usage = 8),
                category("books", "书籍", usage = 2),
            ),
        )

        val viewModel = CategoryDirectoryViewModel(repository)
        advanceUntilIdle()

        assertEquals(
            listOf("咖啡", "书籍", "差旅"),
            viewModel.uiState.value.customCategories.map(CategoryPreference::name),
        )
    }

    @Test
    fun deleteRemovesCategoryAndSignalsVocabularyChange() = runTest(dispatcher) {
        val target = category("coffee", "咖啡", usage = 8)
        val repository = FakeCategoryPreferenceActions(mutableListOf(target))
        val viewModel = CategoryDirectoryViewModel(repository)
        advanceUntilIdle()

        viewModel.delete(target)
        advanceUntilIdle()

        assertEquals(listOf("coffee" to 1L), repository.deleteCalls)
        assertEquals(emptyList(), viewModel.uiState.value.customCategories)
        assertEquals(1, viewModel.uiState.value.changedRevision)
        assertEquals(UiText.res(R.string.category_directory_deleted, "咖啡"), viewModel.uiState.value.message)
        assertEquals(MessageTone.Success, viewModel.uiState.value.messageTone)
    }

    @Test
    fun readOnlyLedgerCannotDelete() = runTest(dispatcher) {
        val target = category("coffee", "咖啡", usage = 8)
        val repository = FakeCategoryPreferenceActions(mutableListOf(target)).apply {
            canModify = false
        }
        val viewModel = CategoryDirectoryViewModel(repository)
        advanceUntilIdle()

        viewModel.delete(target)
        advanceUntilIdle()

        assertEquals(emptyList(), repository.deleteCalls)
        assertEquals(listOf(target), viewModel.uiState.value.customCategories)
        assertEquals(0, viewModel.uiState.value.changedRevision)
    }

    @Test
    fun failedDeleteKeepsCategoryAndClearsBusyState() = runTest(dispatcher) {
        val target = category("coffee", "咖啡", usage = 8)
        val repository = FakeCategoryPreferenceActions(mutableListOf(target)).apply {
            deleteFailure = IllegalStateException()
        }
        val viewModel = CategoryDirectoryViewModel(repository)
        advanceUntilIdle()

        viewModel.delete(target)
        advanceUntilIdle()

        assertEquals(listOf(target), viewModel.uiState.value.customCategories)
        assertNull(viewModel.uiState.value.busyCategoryId)
        assertEquals(UiText.res(R.string.category_directory_delete_failed), viewModel.uiState.value.message)
        assertEquals(MessageTone.Danger, viewModel.uiState.value.messageTone)
    }

    private fun category(
        id: String,
        name: String,
        usage: Int,
    ): CategoryPreference = CategoryPreference(
        publicId = id,
        name = name,
        kind = "custom",
        usageCount = usage,
        rowVersion = 1L,
    )
}

private class FakeCategoryPreferenceActions(
    val items: MutableList<CategoryPreference>,
) : CategoryPreferenceActions {
    var canModify: Boolean = true
    var loadFailure: Throwable? = null
    var deleteFailure: Throwable? = null
    val deleteCalls = mutableListOf<Pair<String, Long>>()

    override fun canModifyLedger(): Boolean = canModify

    override suspend fun categoryPreferences(): Result<List<CategoryPreference>> =
        loadFailure?.let(Result.Companion::failure) ?: Result.success(items.toList())

    override suspend fun deleteCategoryPreference(
        publicId: String,
        expectedRowVersion: Long,
    ): Result<Unit> {
        deleteCalls += publicId to expectedRowVersion
        deleteFailure?.let { return Result.failure(it) }
        items.removeAll { it.publicId == publicId }
        return Result.success(Unit)
    }
}
