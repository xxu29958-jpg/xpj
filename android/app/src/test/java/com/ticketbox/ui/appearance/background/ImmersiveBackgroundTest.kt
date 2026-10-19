package com.ticketbox.ui.appearance.background

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.IntSize
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BackgroundTransform
import com.ticketbox.domain.model.ImmersionMode
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class ImmersiveBackgroundTest {
    @Test
    fun measuredVeilKeepsCanvasTextAtItsContrastTarget() {
        val pixels = listOf(0xFF000000.toInt(), 0xFFFFFFFF.toInt(), 0xFF8EC3E6.toInt(), 0xFFE53935.toInt(), 0xFF2F5D3A.toInt())
        val cases = AppSkin.entries.flatMap { skin -> CanvasTextDemand.entries.flatMap { demand -> pixels.map { Triple(skin, demand, it) } } }
        cases.forEach { (skin, demand, pixel) ->
            val target = canvasTextTarget(skin, demand)
            val veil = canvasVeilColor(skin)
            val need = BackgroundReadability.sampleNeeds(solid(pixel), veil, target).single()
            ImmersionMode.entries.flatMap { mode -> SurfaceRole.entries.map { mode to it } }.forEach { (mode, role) ->
                val alpha = photoVeilAlpha(need, mode, role, skin == AppSkin.Midnight)
                assertTrue(alpha >= need, "The veil never drops below the photo's measured need")
                target.texts.forEach { text ->
                    val ratio = contrastOver(pixel, veil, alpha, text)
                    assertTrue(ratio >= target.ratio - 0.001f, "$skin $demand ${Integer.toHexString(pixel)} $mode $role: $ratio")
                }
            }
        }
    }

    @Test
    fun palePhotosStayVisibleWhileDarkPhotosArePaperVeiledOnlyAsMuchAsNeeded() {
        val target = canvasTextTarget(AppSkin.Paper, CanvasTextDemand.Display)
        val veil = canvasVeilColor(AppSkin.Paper)
        val pale = BackgroundReadability.sampleNeeds(solid(0xFFF1EADF.toInt()), veil, target).single()
        val black = BackgroundReadability.sampleNeeds(solid(0xFF000000.toInt()), veil, target).single()
        assertEquals(0f, pale, "A pale photo already carries the large title")
        assertTrue(black in 0.35f..0.75f, "Large titles over black need a partial, not near-opaque, veil: $black")
    }

    @Test
    fun immersionLevelsAreGenuinelyDifferentAndRestrainedPagesAreCalmer() {
        for (dark in listOf(false, true)) {
            for (need in listOf(0f, 0.2f, 0.5f)) {
                for (role in SurfaceRole.entries) {
                    val atmosphere = photoVeilAlpha(need, ImmersionMode.Atmosphere, role, dark)
                    val balanced = photoVeilAlpha(need, ImmersionMode.Balanced, role, dark)
                    val focus = photoVeilAlpha(need, ImmersionMode.Focus, role, dark)
                    assertTrue(balanced - atmosphere >= 0.06f && focus - balanced >= 0.06f, "$need $role $dark")
                    assertTrue(focus < 1f, "Focus must not erase the user's photo")
                }
                for (mode in ImmersionMode.entries) {
                    assertTrue(photoVeilAlpha(need, mode, SurfaceRole.Edit, dark) > photoVeilAlpha(need, mode, SurfaceRole.Pending, dark))
                    assertTrue(photoVeilAlpha(need, mode, SurfaceRole.Settings, dark) > photoVeilAlpha(need, mode, SurfaceRole.Stats, dark))
                }
            }
        }
    }

    @Test
    fun bandsFollowTheVisibleCropOfTheTransform() {
        // Top half pale, bottom half black: a portrait photo on a portrait viewport.
        val columns = 4
        val rows = 8
        val pixels = IntArray(columns * rows) { index -> if (index / columns < rows / 2) 0xFFF6F2EA.toInt() else 0xFF000000.toInt() }
        val profile = BackgroundTonalProfile.fromArgb(columns, rows, pixels)
        val needs = BackgroundReadability.sampleNeeds(profile, canvasVeilColor(AppSkin.Paper),
            canvasTextTarget(AppSkin.Paper, CanvasTextDemand.Body))
        val image = IntSize(400, 800)
        val viewport = IntSize(400, 800)
        val centered = BackgroundReadability.bandNeeds(needs, profile, PhotoFrame(image, viewport, BackgroundTransform()))
        assertEquals(0f, centered.first())
        assertTrue(centered.last() > 0.8f)
        // Zoomed in and moved to the top of the photo, every band shows the pale half.
        val top = BackgroundReadability.bandNeeds(needs, profile, PhotoFrame(image, viewport, BackgroundTransform(scale = 2f, offsetY = -1f)))
        assertTrue(top.all { it == 0f }, top.joinToString())
    }

    @Test
    fun headerRegionIsMeasuredOverItsOwnPixels() {
        // Pale sky over a dark lower half: the header region shows only the sky.
        val columns = 4
        val rows = 8
        val pixels = IntArray(columns * rows) { index -> if (index / columns < rows / 2) 0xFFEAF3FB.toInt() else 0xFF000000.toInt() }
        val profile = BackgroundTonalProfile.fromArgb(columns, rows, pixels)
        val display = BackgroundReadability.sampleNeeds(profile, canvasVeilColor(AppSkin.Paper),
            canvasTextTarget(AppSkin.Paper, CanvasTextDemand.Display))
        val size = IntSize(400, 800)
        val header = BackgroundReadability.regionNeed(display, profile, PhotoFrame(size, size, BackgroundTransform()), 0 until 160)
        val whole = BackgroundReadability.regionNeed(display, profile, PhotoFrame(size, size, BackgroundTransform()), 0 until 800)
        assertEquals(0f, header, "A pale sky already carries the large title")
        assertTrue(whole > 0.3f, "The whole viewport includes the dark half: $whole")
    }

    @Test
    fun coverageSelectsBySampleCountEvenForTinyBands() {
        assertEquals(0, BackgroundReadability.coveredIndex(1))
        // Two visible cells: covering 97% of them means covering both.
        assertEquals(1, BackgroundReadability.coveredIndex(2))
        assertEquals(96, BackgroundReadability.coveredIndex(100))
        assertEquals(32, BackgroundReadability.coveredIndex(33))
        // A band showing one pale and one black cell is veiled for the black one.
        val profile = BackgroundTonalProfile.fromArgb(2, 1, intArrayOf(0xFFF6F2EA.toInt(), 0xFF000000.toInt()))
        val needs = BackgroundReadability.sampleNeeds(profile, canvasVeilColor(AppSkin.Paper),
            canvasTextTarget(AppSkin.Paper, CanvasTextDemand.Body))
        val size = IntSize(200, 100)
        assertEquals(needs.max(), BackgroundReadability.regionNeed(needs, profile, PhotoFrame(size, size, BackgroundTransform()), 0 until 100))
    }

    @Test
    fun samplingFollowsTheParallaxZoomTheLayerDraws() {
        // Dark top quarter over a pale photo; the parallax zoom pushes the dark rows above the viewport.
        val columns = 2
        val rows = 8
        val pixels = IntArray(columns * rows) { index -> if (index / columns < 2) 0xFF000000.toInt() else 0xFFF6F2EA.toInt() }
        val profile = BackgroundTonalProfile.fromArgb(columns, rows, pixels)
        val needs = BackgroundReadability.sampleNeeds(profile, canvasVeilColor(AppSkin.Paper),
            canvasTextTarget(AppSkin.Paper, CanvasTextDemand.Body))
        val size = IntSize(400, 800)
        val flat = BackgroundReadability.regionNeed(needs, profile, PhotoFrame(size, size, BackgroundTransform()), 0 until 130)
        val zoomed = BackgroundReadability.regionNeed(needs, profile, PhotoFrame(size, size, BackgroundTransform(), depthScale = 2f), 0 until 130)
        assertTrue(flat > 0.8f, "Without zoom the top band shows the dark rows: $flat")
        assertEquals(0f, zoomed, "Zoomed, the top band shows only pale rows")
    }

    @Test
    fun cellExtremesKeepDarkStripesThatOneSampleWouldMiss() {
        val veil = canvasVeilColor(AppSkin.Paper)
        val target = canvasTextTarget(AppSkin.Paper, CanvasTextDemand.Body)
        val pale = 0xFFF6F2EA.toInt()
        val lightOnly = BackgroundReadability.sampleNeeds(BackgroundTonalProfile.fromArgb(1, 1, intArrayOf(pale)), veil, target).single()
        val striped = BackgroundReadability.sampleNeeds(
            BackgroundTonalProfile.fromCellExtremes(1, 1, darkest = intArrayOf(0xFF000000.toInt()), lightest = intArrayOf(pale)), veil, target,
        ).single()
        assertEquals(0f, lightOnly)
        assertTrue(striped > 0.8f, "A cell with dark stripes is protected for them: $striped")
    }

    private fun solid(pixel: Int) = BackgroundTonalProfile.fromArgb(1, 1, intArrayOf(pixel))

    private fun contrastOver(pixel: Int, veil: Color, alpha: Float, text: Color): Float {
        val photo = Color(pixel)
        fun mix(veilChannel: Float, photoChannel: Float) = veilChannel * alpha + photoChannel * (1f - alpha)
        val background = BackgroundReadability.relativeLuminance(
            mix(veil.red, photo.red), mix(veil.green, photo.green), mix(veil.blue, photo.blue))
        return BackgroundReadability.contrast(background, BackgroundReadability.relativeLuminance(text))
    }
}
