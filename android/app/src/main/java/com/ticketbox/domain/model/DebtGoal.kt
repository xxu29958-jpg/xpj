package com.ticketbox.domain.model

/**
 * ADR-0049 §6 (slice 7) debt_repayment goal domain models.
 *
 * A [Goal] with `goalType == "debt_repayment"` carries a [DebtRepaymentEvaluation]
 * (the goal's CURRENT version) instead of the spending-shape numeric fields. The
 * raw backend string values (evaluation state, link fold status, direction,
 * counterparty type) are kept as `String` and mapped to localized labels in the UI
 * layer — mirroring the BillSplit status pattern — with the canonical values pinned
 * by the value objects below so branching/coloring logic does not hardcode literals.
 */
object DebtGoalEvaluationStates {
    const val IN_PROGRESS = "in_progress"
    const val ACHIEVED = "achieved"
    const val NOT_EVALUABLE = "not_evaluable"
}

object DebtLinkStatuses {
    const val OPEN = "open"
    const val CLEARED = "cleared"
    const val VOIDED = "voided"
}

object DebtDirections {
    /** The ledger owner owes the counterparty (owner is the debtor). */
    const val I_OWE = "i_owe"

    /** The counterparty owes the ledger owner (owner is the creditor). */
    const val OWED_TO_ME = "owed_to_me"
}

object DebtCounterpartyTypes {
    const val MEMBER = "member"
    const val EXTERNAL = "external"
}

/**
 * ADR-0049 §7.0 / 8e-6c 外部债还清日期三态（projected-payoff 月 vs 截止月，纯外部债才有，服务端 §4 gate）。
 * [AT_RISK] 是**事实性**的「晚于计划」态，**不是 shame 触发**——UI 渲染琥珀/warn、绝不红，无「更快还清」催促。
 */
object DebtThreeStates {
    const val ON_TRACK = "on_track"
    const val AHEAD = "ahead"
    const val AT_RISK = "at_risk"
}

data class DebtGoalLink(
    val debtPublicId: String,
    val status: String,
    val direction: String,
    val counterpartyType: String,
    val counterpartyLabel: String?,
    val principalAmountCents: Long,
    val remainingAmountCents: Long,
    val homeCurrencyCode: String,
) {
    val isVoided: Boolean get() = status == DebtLinkStatuses.VOIDED
    val isCleared: Boolean get() = status == DebtLinkStatuses.CLEARED
    val isOpen: Boolean get() = status == DebtLinkStatuses.OPEN

    /**
     * 单笔按金额的清偿比例 = (本金 − 剩余) / 本金，钳到 [0,1]（counting-up 渲染，ADR-0049 §6.2 每笔级）。
     * cleared 直接取 1（剩余应为 0）；本金 ≤ 0 的退化数据取 0；冻结的本金/剩余，不读活余额（红线⑥）。
     */
    val clearedFraction: Float
        get() = when {
            isCleared -> 1f
            principalAmountCents <= 0L -> 0f
            else -> ((principalAmountCents - remainingAmountCents).toFloat() / principalAmountCents.toFloat())
                .coerceIn(0f, 1f)
        }
}

/**
 * 还债计划的关联欠款成分（ADR-0049 §6.7）：成员债走关系叙事 + 夹夹撒花；外部债走会计框架；混装降级中性。
 * 全部作废 = [Empty]（无可计入欠款，§6.2 短路空态）。纯客户端按未作废关联欠款的 `counterpartyType` 判定。
 */
enum class DebtGoalComposition { Member, External, Mixed, Empty }

data class DebtRepaymentEvaluation(
    val goalVersion: Int,
    val evaluationState: String,
    val needsReview: Boolean,
    val achievedAt: String?,
    val achievedVersion: Int?,
    val linkedDebts: List<DebtGoalLink>,
    val voidedDebtPublicIds: List<String>,
    // ADR-0049 §7.0 / 8e-6b external-debt payoff projection（纯外部债才有，服务端 gate；成员/混装/数据不足
    // 恒 null）。[trackingDays] = 投影用的观察窗天数（「按最近 N 天」文案）；[projectedPayoffDate] = ISO
    // 日期串（无 Moshi LocalDate adapter 故 String?，同 [achievedAt]）。两者同时有或同时 null。
    val trackingDays: Int? = null,
    val projectedPayoffDate: String? = null,
    // ADR-0049 §7.0 / 8e-6c three-state（纯外部债，服务端 §4 gate）。[targetDate] = 还清日期 ISO 串
    // （未设/非外部恒 null）；[threeState] ∈ {on_track, ahead, at_risk}，仅截止日 + 投影都有时非 null。
    val targetDate: String? = null,
    val threeState: String? = null,
) {
    val isAchieved: Boolean get() = evaluationState == DebtGoalEvaluationStates.ACHIEVED
    val isInProgress: Boolean get() = evaluationState == DebtGoalEvaluationStates.IN_PROGRESS
    val isNotEvaluable: Boolean get() = evaluationState == DebtGoalEvaluationStates.NOT_EVALUABLE

    /** Linked Debts whose fold is still open (not yet cleared, not voided). */
    val openDebts: List<DebtGoalLink> get() = linkedDebts.filter { it.isOpen }

    /** Linked Debts that have been debt-voided (§6/F13 review trigger). */
    val voidedDebts: List<DebtGoalLink> get() = linkedDebts.filter { it.isVoided }

    /**
     * The non-voided link set, as `debt_public_id`s — the replacement set submitted to
     * the link-replace route to take the voided Debt(s) out of the goal (one integrity
     * exit). Empty when every link is voided (the UI must guard: replace needs ≥1 id).
     */
    val nonVoidedDebtPublicIds: List<String>
        get() = linkedDebts.filterNot { it.isVoided }.map { it.debtPublicId }

    // ── ADR-0049 §6 (slice 8e-5) 计划级进度（件数为主视觉，纯客户端，零新后端字段，§6.1/§6.2）─────────

    /** 计入进度分母的关联欠款：作废的不计入（§6.2）。 */
    val countedLinks: List<DebtGoalLink> get() = linkedDebts.filterNot { it.isVoided }

    /** 已「两清」的笔数（含 forgiven——forgive 折叠为 cleared，计入两清，§6.2 P1#3）。 */
    val clearedCount: Int get() = linkedDebts.count { it.isCleared }

    /** 计入进度的总笔数（作废不计入分母，§6.2）。 */
    val totalCount: Int get() = countedLinks.size

    /** 还剩的笔数（未作废、未两清）。 */
    val remainingCount: Int get() = totalCount - clearedCount

    /**
     * 计划级填充比例 = 两清笔数 / 总笔数（**笔数不是金额**：communal「一起做完几件事」=件数，§6.2）。
     * 仅驱动进度条渲染——**不**驱动完成撒花边沿（达成只读服务端 latch，§6.6 / backend F8）。
     */
    val planFraction: Float
        get() = if (totalCount == 0) 0f else (clearedCount.toFloat() / totalCount.toFloat()).coerceIn(0f, 1f)

    /**
     * 计划成分（按未作废关联欠款的对手方类型，§6.7）：全部作废 → [DebtGoalComposition.Empty]；
     * 同时含成员与外部 → [DebtGoalComposition.Mixed]；否则按唯一类型。驱动语气 / 撒花 / 金额呈现的分叉。
     */
    val composition: DebtGoalComposition
        get() {
            val links = countedLinks
            if (links.isEmpty()) return DebtGoalComposition.Empty
            val anyMember = links.any { it.counterpartyType == DebtCounterpartyTypes.MEMBER }
            val anyExternal = links.any { it.counterpartyType != DebtCounterpartyTypes.MEMBER }
            return when {
                anyMember && anyExternal -> DebtGoalComposition.Mixed
                anyMember -> DebtGoalComposition.Member
                else -> DebtGoalComposition.External
            }
        }

    /**
     * 仅当所有未作废关联欠款同一本位币时返回该币种，否则 `null`（混币时金额副文案整条隐藏，§6.2 P2#7）。
     */
    val sharedHomeCurrencyCode: String?
        get() = countedLinks.map { it.homeCurrencyCode }.distinct().singleOrNull()

    /** 未作废关联欠款的本金合计（仅 [sharedHomeCurrencyCode] 非空时有意义）。 */
    val principalSumCents: Long get() = countedLinks.sumOf { it.principalAmountCents }

    /** 未作废关联欠款的剩余合计（仅 [sharedHomeCurrencyCode] 非空时有意义；**永不带「欠」字**呈现，§6.2）。 */
    val remainingSumCents: Long get() = countedLinks.sumOf { it.remainingAmountCents }
}
