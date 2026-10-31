package com.ticketbox.ui.navigation

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.net.Uri
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.MutableState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.ContextCompat
import com.ticketbox.R
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.upload.ReceiptCaptureStore
import java.util.UUID

/** Camera results retain their original file, selection identity and ledger through recreation. */
@Composable
internal fun rememberReceiptCamera(
    shellState: MainShellState, binding: LogicalSessionBinding?, enabled: Boolean,
): () -> Boolean {
    val context = LocalContext.current
    val fields = rememberSaveable { mutableStateOf<ArrayList<String>?>(null) }
    val capture = remember(context.applicationContext, fields) { ReceiptCameraState(context.applicationContext, fields) }
    val currentBinding by rememberUpdatedState(binding)
    val currentEnabled by rememberUpdatedState(enabled)
    val camera = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { capture.complete(it, shellState) }
    val launchCamera = { capture.launch(currentBinding, currentEnabled) { camera.launch(it) } }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) launchCamera() else capture.failure(R.string.widget_camera_permission)
    }
    return {
        val capturedBinding = currentBinding
        if (!currentEnabled || capturedBinding == null) false
        else {
            // A repeated desktop tap cannot start another camera over an unfinished capture.
            if (!capture.pending && capture.begin(capturedBinding)) {
                if (ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) launchCamera()
                else permission.launch(Manifest.permission.CAMERA)
            }
            true
        }
    }
}

private class ReceiptCameraState(private val context: Context, private val fields: MutableState<ArrayList<String>?>) {
    private val store = ReceiptCaptureStore(context)
    val pending get() = fields.value != null
    private fun selection() = fields.value?.let { restoreLaunchRequest(it) as LaunchIntentRequest.ShareImages }

    private fun discard() {
        selection()?.uris?.singleOrNull()?.let { store.release(Uri.parse(it)) }
        fields.value = null
    }

    fun failure(message: Int) {
        discard()
        Toast.makeText(context, message, Toast.LENGTH_LONG).show()
    }

    fun begin(binding: LogicalSessionBinding): Boolean = try {
        val id = UUID.randomUUID().toString()
        val uri = store.create(id)
        fields.value = LaunchIntentRequest.ShareImages(id, listOf(uri.toString())).apply { freezeBinding(binding) }.savedFields()
        true
    } catch (_: java.io.IOException) {
        failure(R.string.widget_camera_failed); false
    } catch (_: RuntimeException) {
        failure(R.string.widget_camera_unavailable); false
    }

    fun launch(binding: LogicalSessionBinding?, enabled: Boolean, open: (Uri) -> Unit) {
        val captured = selection()
        if (captured?.expectedBinding != binding || !enabled) failure(R.string.widget_session_changed)
        else try {
            open(Uri.parse(requireNotNull(captured).uris.single()))
        } catch (_: RuntimeException) {
            failure(R.string.widget_camera_unavailable)
        }
    }

    fun complete(taken: Boolean, shellState: MainShellState) {
        val captured = selection()
        if (!taken) discard()
        else if (captured == null || !store.hasPhoto(Uri.parse(captured.uris.single()))) failure(R.string.widget_camera_failed)
        else {
            // Freeze before leaving the app. A later account/ledger cannot adopt this photo.
            shellState.launchAction.post(LaunchAction.UploadSharedImages(captured))
            fields.value = null
            if (shellState.launchAction.pendingUpload?.selection?.batchId == captured.batchId) shellState.launchAction.retryUpload()
        }
    }
}
