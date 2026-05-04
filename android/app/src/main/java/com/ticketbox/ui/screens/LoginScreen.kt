package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

@Composable
fun LoginScreen(
    message: String?,
    onUnlock: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(24.dp),
        verticalArrangement = Arrangement.Center,
    ) {
        Text("小票夹", style = MaterialTheme.typography.headlineLarge)
        Text(
            "验证后查看账单",
            style = MaterialTheme.typography.bodyLarge,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Button(
            modifier = Modifier
                .fillMaxWidth()
                .padding(top = 24.dp),
            onClick = onUnlock,
        ) {
            Text("指纹/面容解锁")
        }
        message?.let {
            Text(
                text = it,
                modifier = Modifier.padding(top = 12.dp),
                color = MaterialTheme.colorScheme.secondary,
            )
        }
    }
}
