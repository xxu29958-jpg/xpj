package com.ticketbox.ui.appearance.background

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.IntSize
import com.ticketbox.domain.model.BackgroundTransform
import kotlin.math.ceil
import kotlin.math.floor
import kotlin.math.pow

/**
 * What text a page still draws straight on the background canvas. The veil only has to protect
 * that text: pages whose small text sits on reading surfaces keep only large titles on the photo.
 */
enum class CanvasTextDemand {
    /** Small and meta text sits on the canvas: normal-text contrast (4.5:1) for the faintest meta colour. */
    Body,

    /** Only large titles sit on the canvas: large-text contrast (3:1) for the default text colour. */
    Display,
}

/**
 * A small sRGB grid of the decoded photo. Each cell keeps the pixels that are hardest for text in
 * that cell — its darkest and its lightest — taken from every pixel it covers, so a fine texture
 * cannot slip between samples. Blending in the renderer happens on encoded sRGB channels, so the
 * grid keeps them as-is and luminance is only linearised for the contrast check.
 */
class BackgroundTonalProfile(
    val columns: Int,
    val rows: Int,
    private val rgb: FloatArray,
    val samplesPerCell: Int = 1,
) {
    init {
        require(columns > 0 && rows > 0 && samplesPerCell > 0 && rgb.size == columns * rows * samplesPerCell * 3) {
            "Profile grid does not match its size"
        }
    }

    fun red(sample: Int): Float = rgb[sample * 3]
    fun green(sample: Int): Float = rgb[sample * 3 + 1]
    fun blue(sample: Int): Float = rgb[sample * 3 + 2]

    companion object {
        /** One sample per cell from packed ARGB pixels. */
        fun fromArgb(columns: Int, rows: Int, pixels: IntArray): BackgroundTonalProfile =
            BackgroundTonalProfile(columns, rows, packedRgb(pixels))

        /** The darkest and lightest pixel of every cell, both kept as samples of that cell. */
        fun fromCellExtremes(columns: Int, rows: Int, darkest: IntArray, lightest: IntArray): BackgroundTonalProfile {
            require(darkest.size == columns * rows && lightest.size == darkest.size) { "Extremes do not match the grid" }
            val interleaved = IntArray(darkest.size * 2) { if (it % 2 == 0) darkest[it / 2] else lightest[it / 2] }
            return BackgroundTonalProfile(columns, rows, packedRgb(interleaved), samplesPerCell = 2)
        }

        private fun packedRgb(pixels: IntArray): FloatArray {
            val rgb = FloatArray(pixels.size * 3)
            pixels.forEachIndexed { index, pixel ->
                rgb[index * 3] = ((pixel shr 16) and 0xFF) / 255f
                rgb[index * 3 + 1] = ((pixel shr 8) and 0xFF) / 255f
                rgb[index * 3 + 2] = (pixel and 0xFF) / 255f
            }
            return rgb
        }
    }
}

/**
 * Which part of the decoded photo a viewport shows under a transform. [depthScale] is the parallax
 * zoom the photo layer applies around the viewport centre on top of the transform; it enlarges the
 * photo without widening the pan range, exactly as the layer draws it.
 */
data class PhotoFrame(val image: IntSize, val viewport: IntSize, val transform: BackgroundTransform, val depthScale: Float = 1f)

/** Contrast target: every listed text colour the page leaves on the canvas must reach [ratio]. */
data class CanvasTextTarget(val texts: List<Color>, val ratio: Float)

object BackgroundReadability {
    const val BAND_COUNT = 6

    /** Ignore the rarest specks (antialiasing, tiny highlights) instead of veiling the whole page for them. */
    private const val COVERED_PERCENT = 97
    private const val SEARCH_STEPS = 10

    /** Per-cell minimum veil alpha for [target] text, for the hardest sample in the cell; computed once per photo, veil and target. */
    fun sampleNeeds(profile: BackgroundTonalProfile, veil: Color, target: CanvasTextTarget): FloatArray {
        val textLuminances = target.texts.map(::relativeLuminance)
        return FloatArray(profile.columns * profile.rows) { cell ->
            (0 until profile.samplesPerCell).maxOf { veilFor(profile, cell * profile.samplesPerCell + it, veil, textLuminances, target.ratio) }
        }
    }

    /**
     * Minimum veil alpha per horizontal band of the viewport, covering [COVERED_PERCENT] of the
     * photo cells that the current transform actually shows in that band.
     */
    fun bandNeeds(needs: FloatArray, profile: BackgroundTonalProfile, frame: PhotoFrame): FloatArray =
        FloatArray(BAND_COUNT) { band ->
            val top = frame.viewport.height * band / BAND_COUNT
            val bottom = frame.viewport.height * (band + 1) / BAND_COUNT
            regionNeed(needs, profile, frame, top until bottom)
        }

    /**
     * The same coverage rule for one horizontal region of the viewport, such as the shell header
     * band, so a region that only carries large titles is measured over exactly its own pixels.
     */
    fun regionNeed(needs: FloatArray, profile: BackgroundTonalProfile, frame: PhotoFrame, rows: IntRange): Float {
        val (image, viewport, transform) = frame
        if (image.width <= 0 || image.height <= 0 || viewport.width <= 0 || viewport.height <= 0 || rows.isEmpty()) return 0f
        val band = IntSize(viewport.width, rows.last - rows.first + 1)
        val total = BackgroundTransformGeometry.cropBaseScale(viewport, image) * transform.scale * frame.depthScale
        val shift = BackgroundTransformGeometry.maxTranslation(viewport, image, transform)
        val centerX = viewport.width / 2f - transform.offsetX * shift.x
        val centerY = viewport.height / 2f - transform.offsetY * shift.y
        fun column(x: Float) = ((x - centerX) / total + image.width / 2f) / image.width * profile.columns
        fun row(y: Float) = ((y - centerY) / total + image.height / 2f) / image.height * profile.rows
        val left = floor(column(0f)).toInt().coerceIn(0, profile.columns - 1)
        val right = ceil(column(band.width.toFloat())).toInt().coerceIn(left + 1, profile.columns)
        val top = floor(row(rows.first.toFloat())).toInt().coerceIn(0, profile.rows - 1)
        val bottom = ceil(row(rows.last + 1f)).toInt().coerceIn(top + 1, profile.rows)
        val visible = FloatArray((bottom - top) * (right - left))
        var cursor = 0
        for (r in top until bottom) {
            for (c in left until right) visible[cursor++] = needs[r * profile.columns + c]
        }
        visible.sort()
        return visible[coveredIndex(visible.size)]
    }

    /** Index of the smallest value that at least [COVERED_PERCENT] of [count] sorted values do not exceed. */
    internal fun coveredIndex(count: Int): Int = ((count * COVERED_PERCENT + 99) / 100 - 1).coerceIn(0, count - 1)

    /** Smallest veil alpha that lifts one photo sample to the contrast ratio against the text colour. */
    private fun veilFor(profile: BackgroundTonalProfile, index: Int, veil: Color, textLuminances: List<Float>, ratio: Float): Float {
        fun passes(alpha: Float): Boolean {
            val luminance = relativeLuminance(
                blend(profile.red(index), veil.red, alpha),
                blend(profile.green(index), veil.green, alpha),
                blend(profile.blue(index), veil.blue, alpha),
            )
            return textLuminances.all { contrast(luminance, it) >= ratio }
        }
        if (passes(0f)) return 0f
        if (!passes(1f)) return 1f
        var low = 0f
        var high = 1f
        repeat(SEARCH_STEPS) {
            val middle = (low + high) / 2f
            if (passes(middle)) high = middle else low = middle
        }
        return high
    }

    private fun blend(photo: Float, veil: Float, alpha: Float) = veil * alpha + photo * (1f - alpha)

    fun contrast(first: Float, second: Float): Float =
        (maxOf(first, second) + 0.05f) / (minOf(first, second) + 0.05f)

    fun relativeLuminance(color: Color): Float = relativeLuminance(color.red, color.green, color.blue)

    fun relativeLuminance(red: Float, green: Float, blue: Float): Float =
        0.2126f * linear(red) + 0.7152f * linear(green) + 0.0722f * linear(blue)

    private fun linear(channel: Float): Float =
        if (channel <= 0.04045f) channel / 12.92f else ((channel + 0.055f) / 1.055f).pow(2.4f)
}
