package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppSolidCard
import com.ticketbox.ui.design.AppSpacing

@Composable
fun LoginScreen(
    message: UiText?,
    onUnlock: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .safeDrawingPadding()
            .padding(horizontal = AppSpacing.screenHorizontal),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        AuthScreenHeader(
            title = stringResource(R.string.login_header_title),
            subtitle = stringResource(R.string.login_header_subtitle),
        )
        Spacer(Modifier.height(18.dp))
        AppSolidCard(modifier = Modifier.fillMaxWidth()) {
            Column(
                modifier = Modifier.padding(AppSpacing.cardPadding),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Button(
                    modifier = Modifier.fillMaxWidth(),
                    onClick = onUnlock,
                ) {
                    Text(stringResource(R.string.login_unlock_button))
                }
            }
        }
        message?.let {
            Text(
                text = it.asString(),
                modifier = Modifier.padding(top = 12.dp),
                color = MaterialTheme.colorScheme.secondary,
            )
        }
    }
}
