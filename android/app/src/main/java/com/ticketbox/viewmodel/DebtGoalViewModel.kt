package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.DebtAdjustmentActions
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
    val fetchedAt: String? = null,
    val fromCache: Boolean = false,
    val selectedFetchedAt: String? = null,
    val selectedFromCache: Boolean = false,
)

/**
 * ADR-0049 §6.6 (slice 8e-5) 整个还债计划达成的撒花信号（**纯成员计划**才走浮层 + 夹夹）。
 * 由 [DebtGoalViewModel] 在跨「未达成 → 达成」边沿、且成分为纯成员时一次性 emit，[DebtGoalCelebrationOverlay]
 * 消费并播一次 `MascotEvent.MilestoneReached`。外部 / 混装计划达成走轻量 flashMessage（不撒花、不夹夹，§6.7）。
 */
data class DebtGoalCelebration(val goalName: String)

class DebtGoalViewModel(
    private val repository: ReportsActions,
    private val adjustments: DebtAdjustmentActions,
) : ViewModel() {

    private var adjustmentBinding = adjustments.currentAccess()?.binding
    private var adjustmentSnapshotReady = false

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
    private val timezone = java.util.TimeZone.getDefault().id

    // The latest refresh's token. The loading flag is owned by the latest refresh, so a
    // superseded refresh clears it only when no newer refresh has taken over (i.e. it was
    // superseded by openDetail/a mutation) — otherwise the screen could stick "refreshing".
    private var latestRefreshGeneration = 0L

    init {
        viewModelScope.launch {
            adjustments.observeAdjustments().collect { change ->
                val changedBinding = adjustmentBinding != change.binding
                adjustmentBinding = change.binding
                adjustmentSnapshotReady = change.binding != null
                if (change.binding == null) {
                    loadGeneration++
                    _state.value = DebtGoalUiState(canModify = false)
                } else if (changedBinding || change.requiresRefresh) refresh(clearStale = changedBinding)
            }
        }
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
        if (!adjustmentSnapshotReady) {
            _state.update { it.copy(isLoading = adjustments.currentAccess() != null) }
            return
        }
        if (clearStale) {
            _state.update {
                it.copy(goals = emptyList(), selectedGoal = null, error = null, flashMessage = null,
                    fetchedAt = null, fromCache = false, selectedFetchedAt = null, selectedFromCache = false)
            }
        }
        val gen = ++loadGeneration
        val binding = adjustmentBinding
        latestRefreshGeneration = gen
        _state.update { it.copy(isLoading = true, error = null) }
        viewModelScope.launch {
            val result = repository.debtGoals(expectedBinding = binding, timezone = timezone)
            // Drop a load superseded by a newer load or a committed mutation.
            if (gen != loadGeneration || binding != adjustments.currentAccess()?.binding) {
                // Clear our loading flag unless a newer refresh now owns it (else a
                // non-refresh superseder — openDetail / a mutation — would leave the
                // screen stuck refreshing).
                if (gen == latestRefreshGeneration) {
                    _state.update { it.copy(isLoading = false) }
                }
                return@launch
            }
            result.fold(
                onSuccess = { read ->
                    // The complete server list also supplies the open detail's evaluation;
                    // a cached result never creates a newly witnessed achievement.
                    _state.update { current ->
                        val goals = read.value.map { incoming ->
                            current.goals.firstOrNull { it.publicId == incoming.publicId && it.rowVersion > incoming.rowVersion } ?: incoming
                        }
                        val completeRead = goals == read.value
                        current.copy(
                            isLoading = false,
                            canModify = repository.canModifyLedger(),
                            goals = goals,
                            fetchedAt = if (completeRead) read.fetchedAt else current.fetchedAt,
                            fromCache = if (completeRead) read.fromCache else current.fromCache,
                            error = null,
                        )
                    }
                    _state.value.selectedGoal?.let { selected ->
                        val listed = read.value.firstOrNull { it.publicId == selected.publicId }
                        if (listed == null) openDetail(selected)
                        else applyDetailRead(selected, com.ticketbox.data.repository.ReadSnapshot(
                            listed, read.fetchedAt, read.fromCache))
                    }
                },
                onFailure = { err ->
                    _state.update { it.withReadFailure(err) }
                },
            )
        }
    }

    private fun applyDetailRead(old: Goal, read: com.ticketbox.data.repository.ReadSnapshot<Goal>) {
        val fresh = read.value
        if (fresh.rowVersion < old.rowVersion) return
        _state.update { current ->
            if (current.selectedGoal?.publicId == fresh.publicId) current.copy(selectedGoal = fresh,
                goals = current.goals.replaceGoal(fresh),
                selectedFetchedAt = read.fetchedAt, selectedFromCache = read.fromCache)
            else current
        }
        if (!read.fromCache) celebrationController.onGoalApplied(old, fresh)?.let { flash ->
            _state.update { it.copy(flashMessage = flash) }
        }
    }

    /**
     * Open the detail page. Selects optimistically from the list copy, then re-fetches
     * the single goal so the pane uses the canonical row. A failed re-fetch keeps the list copy.
     */
    fun openDetail(goal: Goal) {
        val gen = ++loadGeneration
        val binding = adjustmentBinding
        _state.update { it.copy(selectedGoal = goal, selectedFetchedAt = it.fetchedAt,
            selectedFromCache = it.fromCache) }
        viewModelScope.launch {
            val result = repository.goal(goal.publicId, expectedBinding = binding, timezone = timezone)
            if (gen != loadGeneration || binding != adjustments.currentAccess()?.binding) return@launch
            result.fold(onSuccess = { read -> applyDetailRead(goal, read) }, onFailure = { error -> _state.update { it.withReadFailure(error) } })
        }
    }

    fun closeDetail() {
        _state.update { it.copy(selectedGoal = null, selectedFetchedAt = null, selectedFromCache = false, error = null) }
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
        val binding = adjustmentBinding ?: return
        if (!_state.value.canModify || adjustments.currentAccess()?.binding != binding) return
        _state.update { it.copy(isSubmitting = true, error = null) }
        viewModelScope.launch {
            val result = repository.archiveGoal(goal.publicId, binding)
            if (adjustmentBinding != binding || adjustments.currentAccess()?.binding != binding) return@launch
            result.fold(
                onSuccess = { archived ->
                    // Supersede in-flight loads, drop the detail, and reload the list
                    // (the archived goal falls out of the default list).
                    loadGeneration++
                    _state.update {
                        it.copy(
                            isSubmitting = false,
                            selectedGoal = null,
                            goals = it.goals.filterNot { listed -> listed.publicId == archived.publicId && listed.rowVersion <= archived.rowVersion },
                            fetchedAt = null, fromCache = false, selectedFetchedAt = null, selectedFromCache = false,
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
                        fetchedAt = null, fromCache = false, selectedFetchedAt = null, selectedFromCache = false,
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
