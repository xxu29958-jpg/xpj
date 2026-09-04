package com.ticketbox.ui.components

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.height
import androidx.compose.material3.Text
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.getUnclippedBoundsInRoot
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.theme.TicketboxTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class AppPageStatusInsetTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun shellOwnedStatusInsetIsNotReintroducedByEitherScrollingConsumer() {
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                CompositionLocalProvider(LocalPrimaryStatusInsetHandled provides true) {
                    Column {
                        Box(Modifier.height(56.dp).testTag("domain-bar"))
                        Row {
                            AppScrollableContent(
                                chrome = AppScrollableContentChrome(role = AppPageRole.Stats),
                                refresh = AppScrollableRefreshState(isRefreshing = false, onRefresh = {}),
                                modifier = Modifier.weight(1f),
                            ) {
                                item { Text("First result", Modifier.testTag("list-content")) }
                            }
                            AppPageScrollableColumn(
                                chrome = AppScrollablePageChrome(page = AppPageChrome(role = AppPageRole.Stats)),
                                modifier = Modifier.weight(1f),
                            ) {
                                Text("Filters", Modifier.testTag("column-content"))
                            }
                        }
                    }
                }
            }
        }
        val barBottom = composeRule.onNodeWithTag("domain-bar").getUnclippedBoundsInRoot().bottom
        for (tag in listOf("list-content", "column-content")) {
            val contentTop = composeRule.onNodeWithTag(tag).getUnclippedBoundsInRoot().top
            assertEquals("$tag adds only the normal content gap, not a second status bar", 18f, (contentTop - barBottom).value, 0.5f)
        }
    }
}
