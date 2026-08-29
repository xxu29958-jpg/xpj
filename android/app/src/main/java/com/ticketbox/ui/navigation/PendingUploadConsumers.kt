package com.ticketbox.ui.navigation

import android.content.Context
import android.net.Uri
import com.ticketbox.upload.PreparedUploadImage
import com.ticketbox.upload.prepareScreenshotUpload
import com.ticketbox.viewmodel.PendingUploadAttempt
import com.ticketbox.viewmodel.PendingViewModel
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

internal suspend fun prepareAndUploadSingleImage(
    viewModel: PendingViewModel,
    attempt: PendingUploadAttempt,
    prepare: suspend () -> PreparedUploadImage?,
) {
    try {
        val selected = prepare()
        if (selected == null) {
            viewModel.uploadPreparationFailed(attempt)
            return
        }
        viewModel.uploadScreenshot(selected, attempt)
    } catch (error: CancellationException) {
        viewModel.uploadCancelled(attempt)
        throw error
    } catch (_: Exception) {
        viewModel.uploadPreparationFailed(attempt)
    }
}

/**
 * 顺序上传系统分享带进来的图片。每张：抢 in-progress 锁（[PendingViewModel.beginUploadPreparation]，
 * 同时快照 ledger/generation）→ IO 线程预处理 → await 上传完成 → 再下一张。
 *
 * 第一张若拿不到锁（已有上传在跑）即整体放弃；中途某张预处理失败标记「读不出」并跳过，
 * 不中断其余张。账本切换 / 旧请求作废由 VM 内部守卫处理并停止整批，避免剩余图片跨账本。
 */
internal suspend fun uploadSharedImages(
    context: Context,
    viewModel: PendingViewModel,
    uris: List<String>,
) {
    uploadSharedImageSequence(viewModel, uris) { rawUri ->
        val uri = runCatching { Uri.parse(rawUri) }.getOrNull()
        uri?.let {
            withContext(Dispatchers.IO) { context.prepareScreenshotUpload(it) }
        }
    }
}

/**
 * The production multi-share consumer loop, separated from Android URI IO so
 * its stop/continue and user-feedback semantics can be qualified on the JVM.
 */
internal suspend fun uploadSharedImageSequence(
    viewModel: PendingViewModel,
    imageRefs: List<String>,
    prepare: suspend (String) -> PreparedUploadImage?,
) {
    var attempt: PendingUploadAttempt? = null
    var failedCount = 0
    try {
        for (imageRef in imageRefs) {
            val currentAttempt = viewModel.beginUploadPreparation() ?: return
            attempt = currentAttempt
            when (val prepared = prepareSharedImage(viewModel, currentAttempt, imageRef, prepare)) {
                is SharedImagePreparation.Ready -> {
                    when (uploadSharedImage(viewModel, currentAttempt, prepared.image, failedCount)) {
                        SharedImageUpload.Succeeded -> Unit
                        SharedImageUpload.Failed -> failedCount += 1
                        SharedImageUpload.Stop -> return
                    }
                }
                SharedImagePreparation.Failed -> failedCount += 1
                SharedImagePreparation.Stop -> return
            }
            attempt = null
        }
        viewModel.reportSharedUploadFailures(failedCount)
    } catch (error: CancellationException) {
        attempt?.let(viewModel::uploadCancelled)
        throw error
    }
}

private sealed interface SharedImagePreparation {
    data class Ready(val image: PreparedUploadImage) : SharedImagePreparation
    data object Failed : SharedImagePreparation
    data object Stop : SharedImagePreparation
}

private enum class SharedImageUpload {
    Succeeded,
    Failed,
    Stop,
}

private suspend fun prepareSharedImage(
    viewModel: PendingViewModel,
    attempt: PendingUploadAttempt,
    imageRef: String,
    prepare: suspend (String) -> PreparedUploadImage?,
): SharedImagePreparation = try {
    prepare(imageRef)?.let(SharedImagePreparation::Ready)
        ?: failedSharedImagePreparation(viewModel, attempt)
} catch (error: CancellationException) {
    throw error
} catch (_: Exception) {
    failedSharedImagePreparation(viewModel, attempt)
}

private fun failedSharedImagePreparation(
    viewModel: PendingViewModel,
    attempt: PendingUploadAttempt,
): SharedImagePreparation {
    viewModel.uploadPreparationFailed(attempt)
    return if (viewModel.isUploadAttemptBoundToCurrentLedger(attempt)) {
        SharedImagePreparation.Failed
    } else {
        SharedImagePreparation.Stop
    }
}

private suspend fun uploadSharedImage(
    viewModel: PendingViewModel,
    attempt: PendingUploadAttempt,
    image: PreparedUploadImage,
    priorSharedFailureCount: Int,
): SharedImageUpload {
    if (viewModel.uploadPreparedImage(image, attempt, priorSharedFailureCount)) {
        return SharedImageUpload.Succeeded
    }
    return if (
        viewModel.uiState.value.canRetryUpload ||
        !viewModel.isUploadAttemptBoundToCurrentLedger(attempt)
    ) {
        SharedImageUpload.Stop
    } else {
        SharedImageUpload.Failed
    }
}
