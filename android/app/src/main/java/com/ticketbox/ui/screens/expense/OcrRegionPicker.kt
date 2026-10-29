package com.ticketbox.ui.screens.expense

import android.graphics.BitmapFactory
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.exifinterface.media.ExifInterface
import coil3.compose.AsyncImage
import coil3.request.ImageRequest
import com.ticketbox.R
import com.ticketbox.domain.model.OcrRegionSelection
import com.ticketbox.domain.model.ProtectedImage
import java.io.IOException
import kotlin.math.roundToInt

private enum class RegionGestureMode { Browse, Corners, Drag }

private fun sourceSize(image: ProtectedImage): Size? {
    val options = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    BitmapFactory.decodeByteArray(image.bytes, 0, image.bytes.size, options)
    if (options.outWidth <= 0 || options.outHeight <= 0) return null
    val orientation = try {
        image.bytes.inputStream().use {
            ExifInterface(it).getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL)
        }
    } catch (_: IOException) { return null }
    val swap = orientation in 5..8
    return if (swap) Size(options.outHeight.toFloat(), options.outWidth.toFloat())
    else Size(options.outWidth.toFloat(), options.outHeight.toFloat())
}

@Composable
internal fun OcrRegionPicker(image: ProtectedImage?, expectedHash: String?, enabled: Boolean,
    onDismiss: () -> Unit, onSubmit: (OcrRegionSelection) -> Unit) {
    val source = remember(image) { image?.let(::sourceSize) }
    var selection by rememberSaveable(expectedHash) { mutableStateOf(intArrayOf()) }
    val ready = source != null && expectedHash != null && image?.originalSha256 == expectedHash
    Dialog(onDismissRequest = onDismiss) {
        Surface(shape = MaterialTheme.shapes.large) {
            Column(Modifier.padding(16.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text(stringResource(R.string.ocr_region_open), style = MaterialTheme.typography.titleLarge)
                Text(stringResource(R.string.ocr_region_help))
                if (ready) RegionSelectionImage(requireNotNull(image), requireNotNull(source), selection, enabled) { selection = it }
                else Text(stringResource(if (image == null) R.string.expense_edit_large_image_loading else R.string.expense_edit_large_image_failed))
                Text(stringResource(when (selection.size) {
                    4 -> R.string.ocr_region_selected
                    2 -> R.string.ocr_region_first_corner
                    else -> R.string.ocr_region_empty
                }))
                Row {
                    TextButton(onClick = onDismiss) { Text(stringResource(R.string.ocr_region_cancel)) }
                    TextButton(onClick = { selection = intArrayOf() }, enabled = enabled) { Text(stringResource(R.string.ocr_region_clear)) }
                    TextButton(onClick = { onSubmit(OcrRegionSelection(requireNotNull(expectedHash), selection.toList())) },
                        enabled = ready && enabled && selection.size == 4) { Text(stringResource(R.string.ocr_region_submit)) }
                }
            }
        }
    }
}

@Composable
private fun RegionSelectionImage(image: ProtectedImage, source: Size, selected: IntArray,
    enabled: Boolean, onSelected: (IntArray) -> Unit) {
    var viewport by remember { mutableStateOf(Size.Zero) }
    var start by remember { mutableStateOf(Offset.Zero) }
    var end by remember { mutableStateOf(Offset.Zero) }
    var dragging by remember { mutableStateOf(false) }
    var transform by remember(image.originalSha256) { mutableStateOf(OcrRegionTransform()) }
    var mode by rememberSaveable { mutableStateOf(RegionGestureMode.Browse) }
    val context = LocalContext.current
    val request = remember(image) { ImageRequest.Builder(context).data(image.bytes).size(coil3.size.Size.ORIGINAL).build() }
    val color = MaterialTheme.colorScheme.primary
    FlowRow {
        for ((target, label) in listOf(RegionGestureMode.Browse to R.string.ocr_region_move,
            RegionGestureMode.Corners to R.string.ocr_region_select, RegionGestureMode.Drag to R.string.ocr_region_drag)) {
            TextButton(onClick = { mode = target; dragging = false }, enabled = enabled && target != mode) {
                Text(stringResource(label))
            }
        }
        for ((factor, label) in listOf(.5f to R.string.ocr_region_zoom_out, 2f to R.string.ocr_region_zoom_in)) {
            TextButton(onClick = { transform = transform.adjusted(factor, Offset.Zero,
                Offset(viewport.width / 2, viewport.height / 2), viewport, source) }, enabled = enabled) {
                Text(stringResource(label))
            }
        }
    }
    Box(Modifier.fillMaxWidth().height(320.dp).clipToBounds().onSizeChanged { viewport = Size(it.width.toFloat(), it.height.toFloat()) }) {
        AsyncImage(model = request, contentDescription = stringResource(R.string.ocr_region_help),
            modifier = Modifier.fillMaxSize().graphicsLayer {
                scaleX = transform.zoom; scaleY = transform.zoom
                translationX = transform.pan.x; translationY = transform.pan.y
            }, contentScale = ContentScale.Fit)
        Canvas(Modifier.fillMaxSize().pointerInput(image, enabled, mode, selected.contentHashCode()) {
            if (mode == RegionGestureMode.Browse) detectTransformGestures { centroid, pan, zoom, _ ->
                if (enabled) transform = transform.adjusted(zoom, pan, centroid, viewport, source)
            } else if (mode == RegionGestureMode.Corners) detectTapGestures { point ->
                if (enabled) {
                    val next = transform.sourcePoint(point, viewport, source)
                    if (selected.size == 2) {
                        sourceRectangle(Offset(selected[0].toFloat(), selected[1].toFloat()), next)?.let(onSelected)
                    } else onSelected(intArrayOf(next.x.roundToInt(), next.y.roundToInt()))
                }
            } else detectDragGestures(
                onDragStart = { if (enabled) { start = it; end = it; dragging = true } },
                onDragCancel = { dragging = false },
                onDragEnd = {
                    if (dragging) {
                        val a = transform.sourcePoint(start, viewport, source)
                        val b = transform.sourcePoint(end, viewport, source)
                        sourceRectangle(a, b)?.let(onSelected)
                    }
                    dragging = false
                },
            ) { change, _ -> if (dragging) { end = change.position; change.consume() } }
        }) {
            drawRegionSelection(source, transform, selected, if (dragging) start to end else null, color)
        }
    }
}

private fun sourceRectangle(a: Offset, b: Offset): IntArray? {
    val rect = intArrayOf(minOf(a.x, b.x).roundToInt(), minOf(a.y, b.y).roundToInt(),
        maxOf(a.x, b.x).roundToInt(), maxOf(a.y, b.y).roundToInt())
    return rect.takeIf { it[2] - it[0] >= 4 && it[3] - it[1] >= 4 }
}

private fun DrawScope.drawRegionSelection(source: Size, transform: OcrRegionTransform, selected: IntArray,
    drag: Pair<Offset, Offset>?, color: Color) {
    val scale = transform.scale(size, source)
    val margin = transform.margin(size, source)
    if (selected.size == 2 && drag == null) {
        drawCircle(color, 5.dp.toPx(), margin + Offset(selected[0] * scale, selected[1] * scale))
        return
    }
    val points = drag ?: if (selected.size == 4) {
        (margin + Offset(selected[0] * scale, selected[1] * scale)) to
            (margin + Offset(selected[2] * scale, selected[3] * scale))
    } else return
    val (a, b) = points
    drawRect(color, Offset(minOf(a.x, b.x), minOf(a.y, b.y)),
        Size(kotlin.math.abs(a.x - b.x), kotlin.math.abs(a.y - b.y)), style = Stroke(2.dp.toPx()))
}
