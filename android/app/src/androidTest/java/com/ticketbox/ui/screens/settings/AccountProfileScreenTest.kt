package com.ticketbox.ui.screens.settings

import androidx.compose.runtime.getValue
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertTextContains
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.data.repository.AccountProfile
import com.ticketbox.data.repository.AccountProfileActions
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.AccountProfileViewModel
import org.junit.Rule
import org.junit.Test

class AccountProfileScreenTest {
    @get:Rule val compose = createComposeRule()

    @Test
    fun failedSaveKeepsEditableInputThenExplicitRetryShowsTheAcceptedName() {
        val account = ProfileActions()
        val vm = AccountProfileViewModel(account)
        compose.setContent {
            val state by vm.uiState.collectAsStateWithLifecycle()
            TicketboxTheme(skin = AppSkin.Default) {
                AccountProfileScreen(state, vm::changeName, vm::save, vm::refresh, {})
            }
        }
        compose.runOnIdle { vm.refresh() }
        compose.onNodeWithText("显示名称").performTextReplacement("我的新名称")
        compose.onNodeWithText("保存账号名称").performScrollTo().performClick()
        compose.onNodeWithText("显示名称").assertTextContains("我的新名称")
        compose.onNodeWithText("当前名称：原名称").performScrollTo().assertIsDisplayed()
        compose.runOnIdle { check(vm.uiState.value.message != null); account.fail = false }
        compose.onNodeWithText("保存账号名称").performScrollTo().performClick()
        compose.onNodeWithText("账号名称已保存。").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("当前名称：我的新名称").performScrollTo().assertIsDisplayed()
        compose.runOnIdle { check(account.name == "我的新名称" && account.writes == 2) }
    }

    private class ProfileActions : AccountProfileActions {
        var name = "原名称"
        var fail = true
        var writes = 0
        override fun currentBinding() = LogicalSessionBinding("https://example.test", "ledger", "owner", "session", "binding")
        override suspend fun read(binding: LogicalSessionBinding) = Result.success(AccountProfile("self", name))
        override suspend fun rename(binding: LogicalSessionBinding, name: String, expectedName: String): Result<AccountProfile> {
            writes++
            if (fail) return Result.failure(RepositoryException("连接中断，输入已保留。"))
            check(expectedName == this.name)
            this.name = name
            return Result.success(AccountProfile("self", name))
        }
    }
}
