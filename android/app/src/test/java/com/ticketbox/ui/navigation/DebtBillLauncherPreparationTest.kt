package com.ticketbox.ui.navigation

import android.app.Application
import android.content.ContentProvider
import android.content.ContentValues
import android.content.Context
import android.content.ContextWrapper
import android.content.pm.ProviderInfo
import android.database.MatrixCursor
import android.net.Uri
import android.os.ParcelFileDescriptor
import android.provider.OpenableColumns
import androidx.activity.compose.LocalActivityResultRegistryOwner
import androidx.activity.compose.ManagedActivityResultLauncher
import androidx.activity.result.ActivityResultRegistry
import androidx.activity.result.ActivityResultRegistryOwner
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContract
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.AbstractApplier
import androidx.compose.runtime.BroadcastFrameClock
import androidx.compose.runtime.Composition
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Recomposer
import androidx.compose.runtime.rememberCoroutineScope
import androidx.core.app.ActivityOptionsCompat
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.viewModelScope
import com.ticketbox.viewmodel.DebtCreationDraftStore
import com.ticketbox.viewmodel.DebtDraftField
import com.ticketbox.viewmodel.DebtListViewModel
import com.ticketbox.viewmodel.FakeDebtActions
import java.io.File
import java.io.FileNotFoundException
import java.io.IOException
import java.nio.file.Files
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineExceptionHandler
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlinx.coroutines.withContext
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowContentResolver
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertIs
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
@RunWith(RobolectricTestRunner::class)
@Config(application = Application::class, sdk = [35])
class DebtBillLauncherPreparationTest {
    private val dispatcher = StandardTestDispatcher()
    private val savedState = SavedStateHandle()
    private val repository = FakeDebtActions().apply { listCapability = "CNY" }
    private lateinit var viewModel: DebtListViewModel
    private lateinit var directory: File
    private lateinit var selectedFile: File
    private lateinit var context: Context
    private lateinit var provider: BillPreparationProvider
    private val selectedUri = Uri.parse("content://debt-bill-preparation.test/statement")

    @BeforeTest fun setUp() {
        Dispatchers.setMain(dispatcher)
        directory = Files.createTempDirectory("debt-bill-launcher").toFile()
        selectedFile = File(directory, "original.jpg").apply { writeText("selected original remains owned by provider") }
        val cache = File(directory, "cache").apply { mkdir() }
        val application: Context = RuntimeEnvironment.getApplication()
        context = object : ContextWrapper(application) { override fun getCacheDir() = cache }
        provider = BillPreparationProvider(selectedFile).also {
            it.attachInfo(application, ProviderInfo().apply {
                authority = selectedUri.authority
                exported = true
                grantUriPermissions = true
            })
            ShadowContentResolver.registerProviderInternal(requireNotNull(selectedUri.authority), it)
        }
        viewModel = DebtListViewModel(repository, repository.creation, repository.writes, savedStateHandle = savedState)
    }

    @AfterTest fun tearDown() {
        provider.release.countDown()
        viewModel.viewModelScope.cancel()
        Dispatchers.resetMain()
        directory.deleteRecursively()
    }

    @Test fun providerReadFailureSettlesOnlyTheOriginalPreparationAndKeepsItsDraft() = runTest(dispatcher) {
        advanceUntilIdle()
        assertTrue(viewModel.state.value.homeCurrencyResolved)
        viewModel.updateDraftField(DebtDraftField.Counterparty, "Original lender")
        viewModel.updateDraftField(DebtDraftField.Amount, "125.50")
        val binding = requireNotNull(repository.creation.currentAccess()).binding
        val original = DebtCreationDraftStore(savedState).read(binding)
        val originalBytes = selectedFile.readBytes()
        provider.failRead = true
        val session = LauncherComposition(dispatcher, viewModel, context)
        var preparation: Job? = null
        try {
            advanceUntilIdle()
            preparation = session.select(selectedUri)
            runCurrent()
            provider.awaitEntry()
            assertTrue(viewModel.state.value.isParsingBill)
            provider.release.countDown()
            preparation.join()
            assertTrue(session.failures.all { it is IOException }, session.failures.toString())
            assertEquals(original, DebtCreationDraftStore(savedState).read(binding))
            assertEquals(original.input, viewModel.state.value.addDraft)
            assertContentEquals(originalBytes, selectedFile.readBytes())
            assertEquals(0, provider.deleteCalls)
            assertTrue(context.cacheDir.listFiles().orEmpty().isEmpty())
            assertTrue(repository.parseBillCalls.isEmpty())
            assertTrue(repository.creation.createDrafts.isEmpty())
            assertFalse(viewModel.state.value.isParsingBill, "The actual launcher must settle a failed preparation")
            assertNotNull(viewModel.state.value.error)
        } finally {
            provider.release.countDown()
            preparation?.join()
            session.close()
        }
    }

    @Test fun routeDisposalDuringProviderReadKeepsTheDraftAndCancelsPreparationWithoutAnError() = runTest(dispatcher) {
        advanceUntilIdle()
        assertTrue(viewModel.state.value.homeCurrencyResolved)
        viewModel.updateDraftField(DebtDraftField.Counterparty, "Original lender")
        val binding = requireNotNull(repository.creation.currentAccess()).binding
        val original = DebtCreationDraftStore(savedState).read(binding)
        val originalBytes = selectedFile.readBytes()
        val session = LauncherComposition(dispatcher, viewModel, context)
        var preparation: Job? = null
        try {
            advanceUntilIdle()
            preparation = session.select(selectedUri)
            val completion = CompletableDeferred<Throwable?>()
            preparation.invokeOnCompletion { completion.complete(it) }
            runCurrent()
            provider.awaitEntry()
            assertTrue(viewModel.state.value.isParsingBill)
            session.dispose()
            assertTrue(preparation.isCancelled)
            provider.release.countDown()
            preparation.join()
            assertIs<CancellationException>(completion.await())
            assertTrue(session.failures.isEmpty(), session.failures.toString())
            assertEquals(original, DebtCreationDraftStore(savedState).read(binding))
            assertEquals(original.input, viewModel.state.value.addDraft)
            assertContentEquals(originalBytes, selectedFile.readBytes())
            assertEquals(0, provider.deleteCalls)
            assertTrue(context.cacheDir.listFiles().orEmpty().isEmpty())
            assertTrue(repository.parseBillCalls.isEmpty())
            assertTrue(repository.creation.createDrafts.isEmpty())
            assertFalse(viewModel.state.value.isParsingBill, "Disposal must not strand the retained ViewModel in busy state")
            assertNull(viewModel.state.value.error)
        } finally {
            provider.release.countDown()
            preparation?.join()
            session.close()
        }
    }
}

/** The provider is the only I/O double; the launcher, preparation and ViewModel are production code. */
private class BillPreparationProvider(private val selected: File) : ContentProvider() {
    val entered = CountDownLatch(1)
    val release = CountDownLatch(1)
    var failRead = false
    var deleteCalls = 0

    override fun onCreate() = true
    override fun getType(uri: Uri) = "image/jpeg"
    override fun query(uri: Uri, projection: Array<out String>?, selection: String?,
        selectionArgs: Array<out String>?, sortOrder: String?) =
        MatrixCursor(arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE)).apply {
            addRow(arrayOf(selected.name, selected.length()))
        }
    override fun openFile(uri: Uri, mode: String): ParcelFileDescriptor? {
        entered.countDown()
        check(release.await(10, TimeUnit.SECONDS)) { "Test did not release the provider read" }
        if (failRead) throw FileNotFoundException("Test provider refuses its selected original")
        // The disposal case returns from I/O normally. Actual scope cancellation must still win.
        return null
    }
    override fun insert(uri: Uri, values: ContentValues?): Uri? = null
    override fun update(uri: Uri, values: ContentValues?, selection: String?, selectionArgs: Array<out String>?) = 0
    override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?): Int {
        deleteCalls++
        return 0
    }

    suspend fun awaitEntry() = withContext(Dispatchers.IO) {
        check(entered.await(10, TimeUnit.SECONDS)) { "The actual launcher never reached ContentResolver.openInputStream" }
    }
}

/** Uses the existing effects-only Compose pattern; registry dispatch invokes the registered callback. */
private class LauncherComposition(
    dispatcher: kotlinx.coroutines.CoroutineDispatcher,
    viewModel: DebtListViewModel,
    context: Context,
) {
    val failures = ConcurrentLinkedQueue<Throwable>()
    private val frameClock = BroadcastFrameClock()
    // Observe the old uncaught I/O failure without turning it into a different runTest failure.
    private val host = CoroutineScope(SupervisorJob() + dispatcher + frameClock +
        CoroutineExceptionHandler { _, failure -> failures.add(failure) })
    private val recomposer = Recomposer(host.coroutineContext)
    private val runner = host.launch { recomposer.runRecomposeAndApplyChanges() }
    private var requestCode: Int? = null
    private val registry = object : ActivityResultRegistry() {
        override fun <I, O> onLaunch(requestCode: Int, contract: ActivityResultContract<I, O>, input: I,
            options: ActivityOptionsCompat?) { this@LauncherComposition.requestCode = requestCode }
    }
    private val owner = object : ActivityResultRegistryOwner { override val activityResultRegistry = registry }
    private lateinit var launcher: ManagedActivityResultLauncher<PickVisualMediaRequest, Uri?>
    private lateinit var operationScope: CoroutineScope
    private val composition = Composition(BillLauncherEffectsOnlyApplier(), recomposer).also {
        it.setContent {
            CompositionLocalProvider(LocalActivityResultRegistryOwner provides owner) {
                operationScope = rememberCoroutineScope()
                launcher = rememberDebtBillImageLauncher(viewModel, context, operationScope)
            }
        }
    }

    fun select(uri: Uri): Job {
        launcher.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
        check(registry.dispatchResult(requireNotNull(requestCode), uri))
        return requireNotNull(operationScope.coroutineContext[Job]).children.single()
    }

    fun dispose() = composition.dispose()

    suspend fun close() {
        dispose()
        recomposer.close()
        host.coroutineContext[Job]?.cancelAndJoin()
        runner.join()
    }
}

private class BillLauncherEffectsOnlyApplier : AbstractApplier<Unit>(Unit) {
    override fun insertTopDown(index: Int, instance: Unit) = Unit
    override fun insertBottomUp(index: Int, instance: Unit) = Unit
    override fun remove(index: Int, count: Int) = Unit
    override fun move(from: Int, to: Int, count: Int) = Unit
    override fun onClear() = Unit
}
