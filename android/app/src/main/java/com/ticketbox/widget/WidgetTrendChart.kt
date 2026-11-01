package com.ticketbox.widget

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Paint
import com.ticketbox.R
import com.ticketbox.data.repository.WidgetSpendingTrend
import kotlin.math.abs

/** A small RemoteViews bitmap; negative net spending (refunds) remains below the zero line. */
internal fun widgetTrendChart(context: Context, trend: WidgetSpendingTrend): Bitmap {
    val bitmap = Bitmap.createBitmap(840, 220, Bitmap.Config.ARGB_8888)
    val canvas = Canvas(bitmap)
    val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    val amounts = trend.days.mapNotNull { it.amountMinor?.toDouble() }
    val maximum = amounts.maxOfOrNull { abs(it) }?.coerceAtLeast(1.0) ?: 1.0
    val hasNegative = amounts.any { it < 0 }
    val baseline = if (hasNegative) 104f else 170f
    val height = if (hasNegative) 82f else 148f
    paint.color = context.getColor(R.color.widget_muted)
    paint.alpha = 80
    paint.strokeWidth = 2f
    canvas.drawLine(12f, baseline, 828f, baseline, paint)
    paint.alpha = 255
    trend.days.forEachIndexed { index, day ->
        val center = index * 120f + 60f
        paint.color = context.getColor(R.color.widget_primary)
        val value = day.amountMinor
        if (value != null) {
            val y = baseline - (value.toDouble() / maximum * height).toFloat()
            if (value != 0L) canvas.drawRoundRect(center - 24f, minOf(y, baseline), center + 24f, maxOf(y, baseline), 6f, 6f, paint)
            else canvas.drawCircle(center, baseline, 3f, paint)
        } else {
            paint.color = context.getColor(R.color.widget_muted)
            paint.textAlign = Paint.Align.CENTER
            paint.textSize = 30f
            canvas.drawText("?", center, baseline - 8f, paint)
        }
        paint.color = context.getColor(R.color.widget_muted)
        paint.textAlign = Paint.Align.CENTER
        paint.textSize = 26f
        canvas.drawText("${day.date.monthValue}/${day.date.dayOfMonth}", center, 214f, paint)
    }
    return bitmap
}
