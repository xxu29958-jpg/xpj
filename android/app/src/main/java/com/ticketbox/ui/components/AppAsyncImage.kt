package com.ticketbox.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.DpSize
import androidx.compose.ui.unit.dp
import coil3.compose.AsyncImage
import coil3.request.CachePolicy
import coil3.request.ImageRequest
import coil3.request.crossfade
import com.ticketbox.domain.model.ProtectedImage
import com.ticketbox.ui.design.AppMotion
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.valentinilk.shimmer.shimmer

private const val MAX_PREVIEW_LONG_SIDE = 2048
private const val MAX_PREVIEW_PIXELS = 4_194_304

/**
 * Coil 3 包装的异步图片加载器，统一处理：
 * - crossfade（淡入避免闪白）
 * - shimmer placeholder（加载中骨架）
 * - 内存缓存（滚动列表不重 decode）
 *
 * 用于 [ProtectedImage]（已下载到内存的字节流）。网络图片（如远端原图）
 * 应使用 [AppRemoteAsyncImage]，那个版本走 OkHttp engine 复用 ApiClient
 * 的 auth header（待 Coil OkHttp engine 接入完成后启用）。
 *
 * 注意：Coil 3 接受 ByteArray as data；它会在内部走 ImageRequest 通用 pipeline，
 * 享受缓存。比原始 [android.graphics.BitmapFactory.decodeByteArray] 多了：
 * - 自动 sampling/downscale
 * - LRU memory cache（默认 25% 可用 RAM）
 * - 错误回退到 placeholder
 */
@Composable
fun AppAsyncImage(
    image: ProtectedImage?,
    modifier: Modifier = Modifier,
    placeholder: String = "截图已保存",
    contentDescription: String? = "账单截图",
    shape: Shape = RoundedCornerShape(AppRadius.small),
    contentScale: ContentScale = ContentScale.Crop,
    compact: Boolean = false,
    compactSize: DpSize = DpSize(width = 96.dp, height = 128.dp),
    displayHeight: Dp? = null,
) {
    val context = LocalContext.current
    val request = remember(image) {
        if (image == null) null else {
            ImageRequest.Builder(context)
                .data(image.bytes)
                .crossfade(AppMotion.normalMillis)
                .memoryCachePolicy(CachePolicy.ENABLED)
                .build()
        }
    }
    val sizeModifier = when {
        compact -> Modifier.size(compactSize)
        displayHeight != null -> Modifier.fillMaxWidth().height(displayHeight)
        else -> Modifier.fillMaxWidth().aspectRatio(4f / 5f)
    }

    Box(
        modifier = modifier
            .then(sizeModifier)
            .clip(shape)
            .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.3f)),
        contentAlignment = Alignment.Center,
    ) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .shimmer(),
        ) {
            SkeletonBlock(modifier = Modifier.fillMaxSize(), shape = shape)
        }
        Text(
            text = placeholder,
            modifier = Modifier.padding(AppSpacing.contentGap),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
            textAlign = TextAlign.Center,
        )
        request?.let {
            AsyncImage(
                model = it,
                contentDescription = contentDescription,
                modifier = Modifier.fillMaxSize(),
                contentScale = contentScale,
            )
        }
    }
}

internal fun previewDecodeSampleSize(
    width: Int,
    height: Int,
    maxLongSide: Int = MAX_PREVIEW_LONG_SIDE,
    maxPixels: Int = MAX_PREVIEW_PIXELS,
): Int {
    if (width <= 0 || height <= 0) return 1
    var sampleSize = 1
    while (
        width / sampleSize > maxLongSide ||
        height / sampleSize > maxLongSide ||
        (width.toLong() / sampleSize) * (height.toLong() / sampleSize) > maxPixels
    ) {
        sampleSize *= 2
    }
    return sampleSize
}
