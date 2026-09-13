package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.*
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.test.runTest
import java.net.ConnectException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class GoalQueryCommandInvalidationTest {
    @Test fun everyDirectGoalCommandRetiresOldListsAndUnvisitedDetailsBeforeOfflineReopen() = runTest {
        for (command in GoalReadCommand.entries) {
            val original = command.original()
            val accepted = original.copy(rowVersion = 3, status = if (command == GoalReadCommand.Archive) "archived" else original.status,
                publicId = if (command == GoalReadCommand.CreateDebt) "created-debt-goal" else original.publicId)
            val f = GoalReadFixture { api -> goalCommandApi(api) { accepted } }
            f.api.goals = listOf(original)
            val repository = f.repository
            command.readList(repository).getOrThrow()
            assertEquals(accepted.toDomain(), command.execute(repository, f.binding).getOrThrow())
            f.api.offline = true
            assertTrue(command.readList(repository).isFailure, command.name)
            assertTrue(f.repository.goal(original.publicId).isFailure, command.name)
        }
    }

    @Test fun acceptedArchivePreventsAnAlreadySentListFromRepopulatingTheCache() = runTest {
        val f = GoalReadFixture { api -> goalCommandApi(api) { readGoalDto().copy(status = "archived", rowVersion = 3) } }
        val repository = f.repository
        repository.goals("2026-09").getOrThrow()
        val entered = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        f.api.listResponder = { entered.complete(Unit); release.await(); GoalListResponseDto(listOf(readGoalDto())) }
        val older = async { repository.goals("2026-09") }
        entered.await()
        repository.archiveGoal("goal-jpy", f.binding).getOrThrow()
        release.complete(Unit)
        assertTrue(older.await().isFailure)
        f.api.offline = true
        assertTrue(repository.goals("2026-09").isFailure)
        assertTrue(f.repository.goal("goal-jpy").isFailure)
    }

    @Test fun unacceptedCommandKeepsTheLastConfirmedReadAvailableOffline() = runTest {
        val f = GoalReadFixture { api -> goalCommandApi(api) { throw ConnectException("command not accepted") } }
        val repository = f.repository
        val original = repository.goals("2026-09").getOrThrow()
        assertTrue(repository.archiveGoal("goal-jpy", f.binding).isFailure)
        f.api.offline = true
        assertEquals(original.value, repository.goals("2026-09").getOrThrow().value)
        assertEquals(original.fetchedAt, f.repository.goal("goal-jpy").getOrThrow().fetchedAt)
    }
}

private enum class GoalReadCommand {
    Archive, CreateDebt, ReplaceLinks, AcknowledgeReview, SetTargetDate;

    fun original(): GoalDto = if (this == Archive) readGoalDto() else readGoalDto().copy(
        goalType = "debt_repayment", month = null, targetAmountCents = null, homeCurrencyCode = null,
    )

    suspend fun readList(repository: ReportsRepository) =
        if (this == Archive) repository.goals("2026-09") else repository.debtGoals()

    suspend fun execute(repository: ReportsRepository, binding: LogicalSessionBinding) = when (this) {
        Archive -> repository.archiveGoal("goal-jpy", binding)
        CreateDebt -> repository.createDebtGoal("还清欠款", listOf("debt-1"), binding)
        ReplaceLinks -> repository.replaceDebtLinks("goal-jpy", 2, listOf("debt-2"))
        AcknowledgeReview -> repository.acknowledgeDebtIntegrityReview("goal-jpy", 2)
        SetTargetDate -> repository.setDebtGoalTargetDate("goal-jpy", 2, "2026-12-31")
    }
}

private fun goalCommandApi(delegate: ApiService, accepted: () -> GoalDto): ApiService = object : ApiService by delegate {
    override suspend fun archiveGoal(publicId: String, timezone: String?) = accepted()
    override suspend fun createGoal(request: GoalCreateRequestDto, timezone: String?, idempotencyKey: String?) = accepted()
    override suspend fun replaceGoalDebtLinks(publicId: String, request: DebtGoalLinksReplaceRequestDto,
        idempotencyKey: String?, timezone: String?) = accepted()
    override suspend fun acknowledgeGoalIntegrityReview(publicId: String, request: DebtGoalIntegrityReviewRequestDto,
        idempotencyKey: String?, timezone: String?) = accepted()
    override suspend fun setGoalTargetDate(publicId: String, request: DebtGoalTargetDateRequestDto,
        idempotencyKey: String?, timezone: String?) = accepted()
}
