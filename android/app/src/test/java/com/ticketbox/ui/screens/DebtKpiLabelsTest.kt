package com.ticketbox.ui.screens

import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.DebtRepaymentEvaluation
import com.ticketbox.ui.design.stateTokensForSkin
import java.time.LocalDate
import java.time.ZoneOffset
import java.util.TimeZone
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotSame
import kotlin.test.assertNull
import kotlin.test.assertSame

/**
 * ADR-0049 §7.0 / 8e-6b+6c: the external-debt payoff-date parser ([parsePayoffYearMonth]), the
 * three-state label/tone mappers, and the ISO↔picker-millis conversion. Pure JVM — pins the
 * month-granularity rendering (drop the day to avoid false precision), the honest-fallback contract
 * (unparseable / illegal → null → "数据不足" copy, never a fake date), and the §7.0 去-shame redline
 * (at_risk maps to a non-danger tone kind — the enum has no Danger variant by construction).
 */
class DebtKpiLabelsTest {

    @Test
    fun parsesYearAndMonthDroppingTheDay() {
        assertEquals(2026 to 9, parsePayoffYearMonth("2026-09-01"))
        assertEquals(2026 to 12, parsePayoffYearMonth("2026-12-31"))
        assertEquals(2027 to 1, parsePayoffYearMonth("2027-01-15"))
    }

    @Test
    fun returnsNullForUnparseableOrIllegalMonth() {
        assertNull(parsePayoffYearMonth(""))
        assertNull(parsePayoffYearMonth("2026"))
        assertNull(parsePayoffYearMonth("notadate"))
        assertNull(parsePayoffYearMonth("abcd-09-01")) // non-numeric year
        assertNull(parsePayoffYearMonth("2026-13-01")) // month above range
        assertNull(parsePayoffYearMonth("2026-00-01")) // month below range
    }

    @Test
    fun threeStateLabelMapsEachStateAndDegradesToOnTrack() {
        assertEquals(R.string.debt_three_state_on_track, debtThreeStateLabelRes("on_track"))
        assertEquals(R.string.debt_three_state_ahead, debtThreeStateLabelRes("ahead"))
        assertEquals(R.string.debt_three_state_at_risk, debtThreeStateLabelRes("at_risk"))
        // unknown backend value degrades to on_track rather than crashing.
        assertEquals(R.string.debt_three_state_on_track, debtThreeStateLabelRes("???"))
    }

    @Test
    fun threeStateToneKindKeepsAtRiskOffDanger() {
        // §7.0 去-shame redline (layer 1, structural): at_risk maps to a tone KIND that has no Danger variant.
        assertEquals(DebtThreeStateTone.Ahead, debtThreeStateToneKind("ahead"))
        assertEquals(DebtThreeStateTone.OnTrack, debtThreeStateToneKind("on_track"))
        assertEquals(DebtThreeStateTone.AtRisk, debtThreeStateToneKind("at_risk"))
        assertEquals(DebtThreeStateTone.OnTrack, debtThreeStateToneKind("???"))
    }

    @Test
    fun atRiskToneResolvesToWarnAmberNeverDangerRed() {
        // §7.0 去-shame redline (layer 2, the arm that actually paints the badge): at_risk → warn（琥珀），
        // **绝不** danger（红）。Pin the real color choice — a `tokens.warn → tokens.danger` mutation must fail here.
        val tokens = stateTokensForSkin(AppSkin.Paper)
        assertSame(tokens.warn, debtThreeStateTone(DebtThreeStateTone.AtRisk, tokens))
        assertSame(tokens.success, debtThreeStateTone(DebtThreeStateTone.Ahead, tokens))
        assertSame(tokens.info, debtThreeStateTone(DebtThreeStateTone.OnTrack, tokens))
        assertNotSame(tokens.danger, debtThreeStateTone(DebtThreeStateTone.AtRisk, tokens))
    }

    @Test
    fun payoffLineStateSelectsProjectedStaleOrInsufficient() {
        // 8e-6d display decision (the user-facing heart): the 3 mutually-exclusive backend shapes map to
        // the 3 line states; an unparseable projected date degrades to Insufficient (no fake date, §7.0 R4).
        fun eval(projected: String?, tracking: Int?, stale: Int?) = DebtRepaymentEvaluation(
            goalVersion = 1,
            evaluationState = "in_progress",
            needsReview = false,
            achievedAt = null,
            achievedVersion = null,
            linkedDebts = emptyList(),
            voidedDebtPublicIds = emptyList(),
            trackingDays = tracking,
            projectedPayoffDate = projected,
            daysSinceLastActivity = stale,
        )
        assertEquals(PayoffLineState.Projected(60, 2026, 9), payoffLineState(eval("2026-09-01", 60, null)))
        assertEquals(PayoffLineState.Stale(45), payoffLineState(eval(null, null, 45)))
        assertEquals(PayoffLineState.Insufficient, payoffLineState(eval(null, null, null)))
        // unparseable projected date + no staleness → Insufficient (graceful, never a fabricated date).
        assertEquals(PayoffLineState.Insufficient, payoffLineState(eval("garbage", 60, null)))
    }

    @Test
    fun staleProjectionToneResolvesToWarnAmberNeverDangerRed() {
        // §7.0 去-shame redline (8e-6d): a projection suppressed for staleness ("已 N 天没更新，估算可能
        // 已过期") is a gentle nudge to update, **warn（琥珀）非 danger（红）** — pin the color so a future
        // change can't make it red/alarming. Mirrors the at_risk tone redline.
        val tokens = stateTokensForSkin(AppSkin.Paper)
        assertSame(tokens.warn, debtStaleProjectionTone(tokens))
        assertNotSame(tokens.danger, debtStaleProjectionTone(tokens))
    }

    @Test
    fun isoDateToEpochMillisIsUtcMidnightAndNullsOnGarbage() {
        // Force a NEGATIVE-offset default tz so a `ZoneOffset.UTC → systemDefault()` regression day-drifts and
        // fails — otherwise the assertion can't bite under UTC / Asia/Shanghai (the project's tz off-by-one
        // class, [[feedback_test_month_timezone_alignment]]).
        val previousTz = TimeZone.getDefault()
        try {
            TimeZone.setDefault(TimeZone.getTimeZone("America/New_York"))
            assertEquals(
                LocalDate.of(2026, 9, 1).atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli(),
                isoDateToEpochMillis("2026-09-01"),
            )
            assertNull(isoDateToEpochMillis("not-a-date"))
        } finally {
            TimeZone.setDefault(previousTz)
        }
    }
}
