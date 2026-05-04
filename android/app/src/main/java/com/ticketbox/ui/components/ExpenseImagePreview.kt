package com.ticketbox.ui.components

import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.ProtectedImage

@Composable
fun ExpenseImagePreview(
    image: ProtectedImage?,
    modifier: Modifier = Modifier,
    placeholder: String = "截图已上传",
    contentDescription: String = "账单截图",
) {
    val imageBitmap = remember(image) {
        image?.bytes?.let { bytes ->
            BitmapFactory.decodeByteArray(bytes, 0, bytes.size)?.asImageBitmap()
        }
    }
    val previewAspectRatio = remember(imageBitmap) {
        val bitmap = imageBitmap
        if (bitmap == null || bitmap.height == 0) {
            4f / 5f
        } else {
            (bitmap.width.toFloat() / bitmap.height.toFloat()).coerceIn(0.75f, 1.45f)
        }
    }

    if (imageBitmap == null) {
        Box(
            modifier = modifier
                .fillMaxWidth()
                .aspectRatio(4f / 5f)
                .clip(RoundedCornerShape(12.dp))
                .background(MaterialTheme.colorScheme.surfaceVariant),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text = placeholder,
                modifier = Modifier.padding(16.dp),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodyMedium,
            )
        }
        return
    }

    Image(
        bitmap = imageBitmap,
        contentDescription = contentDescription,
        modifier = modifier
            .fillMaxWidth()
            .aspectRatio(previewAspectRatio)
            .clip(RoundedCornerShape(12.dp))
            .background(MaterialTheme.colorScheme.surfaceVariant),
        contentScale = ContentScale.Fit,
    )
}
