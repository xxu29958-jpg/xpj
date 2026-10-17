package com.ticketbox.ui.appearance.background

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.Path
import android.graphics.Shader
import java.io.File
import kotlin.random.Random

/** Writes a deterministic synthetic photo; background evidence never uses a real user image. */
internal fun writeControlledPhoto(file: File, width: Int, height: Int, paint: (Canvas, Int, Int) -> Unit): File {
    val bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
    paint(Canvas(bitmap), width, height)
    file.outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
    bitmap.recycle()
    return file
}

/** Controlled photo scenes: mixed landscape, pale, dark, high saturation and busy texture. */
internal object ControlledPhotos {
    fun scene(canvas: Canvas, width: Int, height: Int) {
        val w = width.toFloat()
        val h = height.toFloat()
        canvas.drawRect(0f, 0f, w, h, Paint().apply {
            shader = LinearGradient(0f, 0f, 0f, h * 0.6f, 0xFF8EC3E6.toInt(), 0xFFF7E3C2.toInt(), Shader.TileMode.CLAMP)
        })
        canvas.drawCircle(w * 0.72f, h * 0.30f, h * 0.09f, Paint(Paint.ANTI_ALIAS_FLAG).apply { color = 0xFFFFD27A.toInt() })
        fun hill(color: Int, base: Float, peak: Float, shift: Float) = canvas.drawPath(Path().apply {
            moveTo(0f, h); lineTo(0f, h * base)
            quadTo(w * (0.3f + shift), h * peak, w * 0.6f, h * base)
            quadTo(w * (0.85f + shift), h * (base + 0.08f), w, h * (base - 0.05f))
            lineTo(w, h); close()
        }, Paint(Paint.ANTI_ALIAS_FLAG).apply { this.color = color })
        hill(0xFF5E8C5A.toInt(), 0.62f, 0.38f, 0f)
        hill(0xFF2F5D3A.toInt(), 0.74f, 0.52f, 0.1f)
        canvas.drawRect(0f, h * 0.86f, w, h, Paint().apply { color = 0xFF3E7CA6.toInt() })
    }

    fun pale(canvas: Canvas, width: Int, height: Int) {
        canvas.drawRect(0f, 0f, width.toFloat(), height.toFloat(), Paint().apply {
            shader = LinearGradient(0f, 0f, 0f, height.toFloat(), 0xFFFFFFFF.toInt(), 0xFFF1EADF.toInt(), Shader.TileMode.CLAMP)
        })
        val cloud = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = 0xFFEDE7F6.toInt() }
        listOf(0.2f to 0.18f, 0.7f to 0.42f, 0.35f to 0.7f).forEach { (x, y) ->
            canvas.drawCircle(width * x, height * y, width * 0.22f, cloud)
        }
    }

    fun dark(canvas: Canvas, width: Int, height: Int) {
        canvas.drawRect(0f, 0f, width.toFloat(), height.toFloat(), Paint().apply {
            shader = LinearGradient(0f, 0f, 0f, height.toFloat(), 0xFF0B0E14.toInt(), 0xFF1B2233.toInt(), Shader.TileMode.CLAMP)
        })
        val random = Random(7)
        val light = Paint(Paint.ANTI_ALIAS_FLAG)
        repeat(260) {
            light.color = if (random.nextBoolean()) 0xFFFFC86B.toInt() else 0xFFE8F1FF.toInt()
            canvas.drawCircle(random.nextFloat() * width, height * (0.45f + random.nextFloat() * 0.55f), 2f + random.nextFloat() * 5f, light)
        }
    }

    fun saturated(canvas: Canvas, width: Int, height: Int) {
        val colors = listOf(0xFFE53935, 0xFFFB8C00, 0xFFFDD835, 0xFF43A047, 0xFF1E88E5, 0xFF8E24AA)
        val band = width / colors.size.toFloat()
        colors.forEachIndexed { index, color ->
            canvas.drawRect(index * band, 0f, (index + 1) * band, height.toFloat(), Paint().apply { this.color = color.toInt() })
        }
    }

    fun busy(canvas: Canvas, width: Int, height: Int) {
        val random = Random(11)
        val paint = Paint()
        repeat(2400) {
            paint.color = (0xFF000000 or random.nextLong(0xFFFFFF)).toInt()
            val x = random.nextFloat() * width
            val y = random.nextFloat() * height
            canvas.drawRect(x, y, x + 6f + random.nextFloat() * 40f, y + 4f + random.nextFloat() * 18f, paint)
        }
        paint.color = 0xFF111111.toInt()
        paint.strokeWidth = 2f
        var y = 0f
        while (y < height) {
            canvas.drawLine(0f, y, width.toFloat(), y, paint)
            y += 22f
        }
    }

}
