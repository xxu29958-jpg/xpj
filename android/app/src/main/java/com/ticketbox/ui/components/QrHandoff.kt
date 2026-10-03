package com.ticketbox.ui.components

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.QrCodeScanner
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.google.zxing.BarcodeFormat
import com.google.zxing.EncodeHintType
import com.google.zxing.client.android.Intents
import com.google.zxing.common.BitMatrix
import com.google.zxing.qrcode.QRCodeWriter
import com.google.zxing.qrcode.decoder.ErrorCorrectionLevel
import com.journeyapps.barcodescanner.BarcodeEncoder
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import com.ticketbox.R
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/** Plaintext and bitmap live only with their existing one-time result surface. */
@Composable
fun HandoffQrCode(content: String, description: String) {
    val image by produceState<Result<ImageBitmap>?>(null, content) {
        value = null
        value = withContext(Dispatchers.Default) {
            runCatching { BarcodeEncoder().createBitmap(handoffQrMatrix(content)).asImageBitmap() }
        }
    }
    image?.fold(
        onSuccess = { Image(bitmap = it, contentDescription = description,
            modifier = Modifier.widthIn(max = 248.dp).fillMaxWidth()) },
        onFailure = { Text(stringResource(R.string.qr_display_failed)) },
    )
}

internal fun handoffQrMatrix(content: String): BitMatrix = QRCodeWriter().encode(
    content, BarcodeFormat.QR_CODE, 480, 480,
    mapOf(EncodeHintType.CHARACTER_SET to "UTF-8", EncodeHintType.MARGIN to 4,
        EncodeHintType.ERROR_CORRECTION to ErrorCorrectionLevel.M),
)

/** The embedded scanner works offline and does not save a camera image. */
@Composable
fun ScanQrButton(label: String, enabled: Boolean, onResult: (String) -> Unit) {
    var cameraUnavailable by remember { mutableStateOf(false) }
    val prompt = stringResource(R.string.qr_scan_prompt)
    val scanner = rememberLauncherForActivityResult(ScanContract()) { result ->
        cameraUnavailable = result.originalIntent?.getBooleanExtra(Intents.Scan.MISSING_CAMERA_PERMISSION, false) == true
        result.contents?.let(onResult)
    }
    AppSecondaryButton(text = label, leadingIcon = Icons.Default.QrCodeScanner, enabled = enabled,
        modifier = Modifier.fillMaxWidth(), onClick = {
            cameraUnavailable = false
            scanner.launch(ScanOptions().setDesiredBarcodeFormats(ScanOptions.QR_CODE).setPrompt(prompt)
                .setBeepEnabled(false).setBarcodeImageEnabled(false).setOrientationLocked(false))
        })
    if (cameraUnavailable) Text(stringResource(R.string.qr_camera_unavailable))
}
