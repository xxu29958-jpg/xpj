package com.ticketbox.ui.components

import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.unit.dp
import com.ticketbox.R

/** Quiet receipt art shared by genuine empty states; text owns the state meaning. */
@Composable
fun ReceiptEmptyIllustration(modifier: Modifier = Modifier) {
    Image(
        painter = painterResource(R.drawable.receipt_tray),
        contentDescription = null,
        modifier = modifier
            .size(width = 144.dp, height = 96.dp)
            .clearAndSetSemantics {},
    )
}
