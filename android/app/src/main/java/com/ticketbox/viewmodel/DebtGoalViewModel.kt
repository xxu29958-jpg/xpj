package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.ReportsActions
import com.ticketbox.domain.model.DebtGoalComposition
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.ZoneOffset

/**
 * ADR-0049 §6 (slice 7) debt_repayment goal screen state + actions.
 *
 * Reuses the goal repository ([ReportsActions]) — a debt_repayment goal is a goal
 * (same table / DTO). The screen is a list → detail flow inside one overlay; the
 * detail surfaces the §6/F13 integrity review with its two exits:
 *  - remove the debt-voided link(s) via [removeVoidedDebts] (link-replace → new version)
 *  - keep it for audit via [acknowledge] (clears needs_review for the current version)
 *
 * This slice is view + integrity-review only; creating a debt goal (which needs a
 * Debt picker) lands with the broader debt-management UI in a later slice.
 */
data class DebtGoalUiState(
    val isLoading: Boolean = false,
    val canModify: Boolean = true,
    val goals: List<Goal> = emptyList(),
    /** Non-null = the detail page for this goal is open; null = the list. */
    val selectedGoal: Goal? = null,
    val isSubmitting: Boolean = false,
    val error: UiText? = null,
    val flashMessage: UiText? = null,
)

/**
 * ADR-0049 §6.6 (slice 8e-5) 整个还债计划达成的撒花信号（**纯成员计划**才走浮层 + 夹夹）。
 * 由 [DebtGoalViewModel] 在跨「未达成 → 达成」边沿、且成分为纯成员时一次性 emit，[DebtGoalCelebrationOverlay]
 * 消费并播一次 `MascotEvent.MilestoneReached`。外部 / 混装计划达成走轻量 flashMessage（不撒花、不夹夹，§6.7）。
 */
data class DebtGoalCelebration(val goalName: String)

class DebtGoalViewModel(
    private val repository: ReportsActions,
) : ViewModel() {

    private val _state = MutableStateFlow(DebtGoalUiState(canModify = repository.canModifyLedger()))
    val state: StateFlow<DebtGoalUiState> = _state.asStateFlow()

    // ADR-0049 §6.6 计划达成撒花：边沿判定 + 去重 + 撒花信号收进窄职责协作者，而非把 VM 撑过 detekt
    // TooManyFunctions 门（豁免≠把类做胖，[[feedback_baseline_not_complexity_license]]）。celebration 属性
    // 直接转发协作者的 flow（property，不计入 TooManyFunctions）。
    private val celebrationController = DebtGoalCelebrationController()
    val celebration: StateFlow<DebtGoalCelebration?> get() = celebrationController.celebration

    // Monotonic load token (mirrors StatsReportsViewModel): a load applies its result
    // only if it is still the latest. Overlapping loads (init + refresh(clearStale=true)
    // on overlay (re-)entry, pull-to-refresh) and committed mutations bump it, so a slow
    // earlier load can't revert a just-applied review to a stale row_version (→ a 409 next).
    private var loadGeneration = 0L

    // The latest refresh's token. The loading flag is owned by the latest refresh, so a
    // superseded refresh clears it only when no newer refresh has taken over (i.e. it was
    // superseded by openDetail/a mutation) — otherwise the screen could stick "refreshing".
    private var latestRefreshGeneration = 0L

    init {
        refresh()
    }

    /**
     * Re-fetch the debt goals. [clearStale] = true first clears any prior ledger's debt goals
     * (the overlay (re-)open path): the VM is cached across the overlay's open/close and survives a
     * ledger switch in Settings, so the previous ledger's debt links — which carry counterparties
     * and amounts — must never linger under a new ledger (ledger-isolation boundary); clearing up
     * front avoids briefly showing stale cross-ledger data. [clearStale] = false is the plain
     * pull-to-refresh / in-place re-fetch (it keeps the open detail to re-latch it).
     */
    fun refresh(clearStale: Boolean = false) {
        if (clearStale) {
            _state.update {
                it.copy(goals = emptyList(), selectedGoal = null, error = null, flashMessage = null)
            }
        }
        val gen = ++loadGeneration
        latestRefreshGeneration = gen
        _state.update { it.copy(isLoading = true, error = null) }
        viewModelScope.launch {
            val result = repository.debtGoals()
            // Drop a load superseded by a newer load or a committed mutation.
            if (gen != loadGeneration) {
                // Clear our loading flag unless a newer refresh now owns it (else a
                // non-refresh superseder — openDetail / a mutation — would leave the
                // screen stuck refreshing).
                if (gen == latestRefreshGeneration) {
                    _state.update { it.copy(isLoading = false) }
                }
                return@launch
            }
            result.fold(
                onSuccess = { goals ->
                    // Do NOT derive selectedGoal from the list: the list path is read-only
                    // (it never latches an all-cleared debt goal — only GET /api/goals/{id}
                    // does), so re-latch the open detail via the detail endpoint below.
                    _state.update { current ->
                        current.copy(
                            isLoading = false,
                            canModify = repository.canModifyLedger(),
                            goals = goals,
                            error = null,
                        )
                    }
                    if (_state.value.selectedGoal == null) {
                        val refreshed = refreshedDebtGoalList(repository, goals)
                        if (gen != loadGeneration) return@launch
                        val refreshedById = refreshed.associateBy { it.publicId }
                        _state.update { current ->
                            if (current.selectedGoal != null) {
                                current
                            } else {
                                current.copy(goals = current.goals.map { refreshedById[it.publicId] ?: it })
                            }
                        }
                    } else {
                        latchSelectedDetail(gen)
                    }
                },
                onFailure = { err ->
                    _state.update {
                        it.copy(isLoading = false, error = err.toUiText(R.string.debt_goal_load_failed))
                    }
                },
            )
        }
    }

    /**
     * Re-fetch the open detail through the latching detail endpoint after a list load.
     * The list path does not persist achievement (ADR-0049 §6: writer-gated latch lives
     * only on GET /api/goals/{id}), so syncing an achieved detail from the list would show
     * an unlatched "achieved" — a later reopen/void would then never have recorded
     * achieved_version, breaking sticky achievement. Generation-guarded like the others.
     */
    private suspend fun latchSelectedDetail(gen: Long) {
        val selected = _state.value.selectedGoal ?: return
        val fresh = repository.goal(selected.publicId).getOrNull() ?: return
        if (gen != loadGeneration) return
        _state.update { current ->
            if (current.selectedGoal?.publicId == fresh.publicId) {
                current.copy(selectedGoal = fresh, goals = current.goals.replaceGoal(fresh))
            } else {
                current
            }
        }
        // 主路径：详情停在 in_progress 时一次 refresh 拉到 achieved（用户在场目击跨边沿，§6.6）。
        // 成员达成 emit overlay 撒花信号；外部/混装返回轻量 flash 文案就展示（§6.7）。
        celebrationController.onGoalApplied(old = selected, new = fresh)?.let { flash ->
            _state.update { it.copy(flashMessage = flash) }
        }
    }

    /**
     * Open the detail page. Selects optimistically from the list copy, then re-fetches
     * the single goal: a writer GET latches achievement server-side (ADR-0049 §6), so
     * opening the detail is the trigger. A failed re-fetch keeps the list copy.
     */
    fun openDetail(goal: Goal) {
        val gen = ++loadGeneration
        _state.update { it.copy(selectedGoal = goal) }
        viewModelScope.launch {
            val fresh = repository.goal(goal.publicId).getOrNull() ?: return@launch
            // A newer load/mutation superseded this detail fetch — don't clobber it.
            if (gen != loadGeneration) return@launch
            _state.update { current ->
                if (current.selectedGoal?.publicId == fresh.publicId) {
                    current.copy(selectedGoal = fresh, goals = current.goals.replaceGoal(fresh))
                } else {
                    current
                }
            }
            // The list copy never latches (only the writer GET does); so opening a goal whose
            // list copy is in_progress but whose fresh detail just turned achieved is a
            // witnessed cross-edge. An already-achieved list copy → no edge (no spurious replay).
            celebrationController.onGoalApplied(old = goal, new = fresh)?.let { flash ->
                _state.update { it.copy(flashMessage = flash) }
            }
        }
    }

    fun closeDetail() {
        _state.update { it.copy(selectedGoal = null, error = null) }
    }

    /** §6/F13 exit (a): drop the debt-voided link(s) → a new goal version. */
    fun removeVoidedDebts() {
        val goal = _state.value.selectedGoal ?: return
        val evaluation = goal.debtRepayment ?: return
        val keep = evaluation.nonVoidedDebtPublicIds
        if (keep.isEmpty()) {
            // A debt goal must keep ≥1 link; every link voided has no clean replacement.
            _state.update { it.copy(error = UiText.res(R.string.debt_goal_remove_voided_needs_one)) }
            return
        }
        _state.update { it.copy(isSubmitting = true, error = null) }
        viewModelScope.launch {
            val result = repository.replaceDebtLinks(goal.publicId, goal.rowVersion, keep)
            applyMutation(result, R.string.debt_goal_links_updated)
        }
    }

    /** §6/F13 exit (b): acknowledge ("keep for audit") → clears needs_review. */
    fun acknowledge() {
        val goal = _state.value.selectedGoal ?: return
        _state.update { it.copy(isSubmitting = true, error = null) }
        viewModelScope.launch {
            val result = repository.acknowledgeDebtIntegrityReview(goal.publicId, goal.rowVersion)
            applyMutation(result, R.string.debt_goal_review_acknowledged)
        }
    }

    /**
     * ADR-0049 §7.0 / 8e-6c: set ([epochMillis] non-null, the Material3 picker's UTC millis) or
     * clear ([epochMillis] = null) the open debt goal's payoff deadline. Reuses [applyMutation]
     * (same OCC fold-after shape as the integrity exits) so it never un-achieves the goal — the
     * server bumps row_version only. Only reachable from the pure-external KPI block (the UI gates
     * the affordance on composition == External), so a member/mixed plan can never set a deadline.
     */
    fun setTargetDate(epochMillis: Long?) {
        val goal = _state.value.selectedGoal ?: return
        _state.update { it.copy(isSubmitting = true, error = null) }
        viewModelScope.launch {
            val targetDate = epochMillis?.let(::epochMillisToIsoDate)
            val result = repository.setDebtGoalTargetDate(goal.publicId, goal.rowVersion, targetDate)
            applyMutation(result, R.string.debt_goal_target_date_updated)
        }
    }

    /**
     * Archive the open goal. The only clean exit when a not-yet-achieved goal's whole
     * link set is voided (§6/F13): "remove voided" has no non-voided replacement and
     * acknowledge is achieved-only, so without a Debt picker (a later slice) archiving
     * is how the user clears the dead-end review.
     */
    fun archiveSelected() {
        val goal = _state.value.selectedGoal ?: return
        if (!_state.value.canModify) return
        _state.update { it.copy(isSubmitting = true, error = null) }
        viewModelScope.launch {
            repository.archiveGoal(goal.publicId).fold(
                onSuccess = {
                    // Supersede in-flight loads, drop the detail, and reload the list
                    // (the archived goal falls out of the default list).
                    loadGeneration++
                    _state.update {
                        it.copy(
                            isSubmitting = false,
                            selectedGoal = null,
                            flashMessage = UiText.res(R.string.debt_goal_archived),
                            error = null,
                        )
                    }
                    refresh()
                },
                onFailure = { err ->
                    _state.update {
                        it.copy(isSubmitting = false, error = err.toUiText(R.string.debt_goal_update_failed))
                    }
                },
            )
        }
    }

    fun dismissFlash() {
        _state.update { it.copy(flashMessage = null) }
    }

    private fun applyMutation(result: Result<Goal>, successRes: Int) {
        result.fold(
            onSuccess = { updated ->
                // Supersede any in-flight load so it can't revert this committed change.
                loadGeneration++
                val previous = _state.value.selectedGoal
                _state.update { current ->
                    current.copy(
                        isSubmitting = false,
                        selectedGoal = updated,
                        goals = current.goals.replaceGoal(updated),
                        flashMessage = UiText.res(successRes),
                        error = null,
                    )
                }
                // removeVoidedDebts that completes the (new-version) plan is a user-caused,
                // witnessed completion → celebrate (the external/mixed flash may overwrite the
                // generic mutation flash; the member case emits the overlay signal instead).
                celebrationController.onGoalApplied(old = previous, new = updated)?.let { flash ->
                    _state.update { it.copy(flashMessage = flash) }
                }
            },
            onFailure = { err ->
                _state.update {
                    it.copy(isSubmitting = false, error = err.toUiText(R.string.debt_goal_update_failed))
                }
            },
        )
    }

    /** Overlay 消费撒花信号后清空（动画播完 / 离屏 dispose 时调用，镜像 DebtDetailViewModel）。 */
    fun consumeCelebration() {
        celebrationController.consume()
    }
}

/**
 * The list endpoint is read-only and intentionally does not persist a freshly completed
 * debt_repayment goal. Fetch listed goals through the detail endpoint once so a fully repaid plan
 * reflects as achieved in the list without requiring the user to open every goal manually.
 */
private suspend fun refreshedDebtGoalList(repository: ReportsActions, listedGoals: List<Goal>): List<Goal> =
    listedGoals.map { goal -> repository.goal(goal.publicId).getOrNull() ?: goal }

/**
 * ADR-0049 §6.6 计划达成撒花的边沿判定 + 去重 + 撒花信号的窄职责协作者（从 [DebtGoalViewModel] 抽出，
 * 而非把 VM 撑过 detekt TooManyFunctions 门——豁免≠把类做胖，[[feedback_baseline_not_complexity_license]]）。
 *
 * **达成只读服务端 `evaluation_state`**（latch + sticky，backend F8）——**禁止**用客户端
 * `clearedCount==totalCount` 当完成信号（client 可能比 latch 早一拍）。边沿 = 旧态非 achieved → 新态
 * achieved；旧态缺失（无可比较）或已 achieved（sticky 重放）都不撒。per (publicId, goal_version) 去重。
 * 成分自适应（§6.7）：纯成员 → emit [celebration]（浮层撒花 + 由 overlay 发夹夹）；外部 / 混装 → 返回
 * 轻量 flash 文案给 VM 展示（不撒花、不夹夹，避免给信用卡撒花的违和）。
 */
internal class DebtGoalCelebrationController {
    private val _celebration = MutableStateFlow<DebtGoalCelebration?>(null)
    val celebration: StateFlow<DebtGoalCelebration?> = _celebration.asStateFlow()

    // per (publicId, goal_version) 去重；link-replace 产生新 goal_version → 新版本若再次达成是新撒花机会。
    private val celebratedKeys = mutableSetOf<String>()

    /**
     * 在一次「goal 应用」后判定是否跨达成边沿。纯成员达成 emit [celebration]（返回 null）；外部 / 混装
     * 达成返回需展示的 flash 文案；无边沿 / 重放 / 已达成 / 全作废都返回 null。
     */
    fun onGoalApplied(old: Goal?, new: Goal): UiText? {
        val newEval = new.debtRepayment ?: return null
        if (!newEval.isAchieved) return null
        val oldEval = old?.debtRepayment ?: return null
        if (oldEval.isAchieved) return null
        if (!celebratedKeys.add("${new.publicId}:${newEval.goalVersion}")) return null
        return when (newEval.composition) {
            DebtGoalComposition.Member -> {
                _celebration.update { DebtGoalCelebration(goalName = new.name) }
                null
            }
            DebtGoalComposition.External -> UiText.res(R.string.debt_plan_complete_external)
            DebtGoalComposition.Mixed -> UiText.res(R.string.debt_plan_complete_mixed)
            // 不可达：达成必有 ≥1 非作废 cleared 链，成分不会是 Empty（防御性兜底）。
            DebtGoalComposition.Empty -> null
        }
    }

    fun consume() {
        _celebration.update { null }
    }
}

private fun List<Goal>.replaceGoal(updated: Goal): List<Goal> =
    map { if (it.publicId == updated.publicId) updated else it }

/**
 * Material3 date-picker UTC epoch-millis → ISO `yyyy-MM-dd` (the wire shape the backend deadline
 * expects). UTC throughout (the picker reports the selected day as UTC-midnight millis) so the
 * calendar day never drifts across a timezone boundary.
 */
private fun epochMillisToIsoDate(epochMillis: Long): String =
    Instant.ofEpochMilli(epochMillis).atZone(ZoneOffset.UTC).toLocalDate().toString()
