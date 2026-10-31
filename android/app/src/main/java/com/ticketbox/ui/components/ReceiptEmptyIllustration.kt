package com.ticketbox.ui.components

import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

/** Quiet 票盒 art shared by genuine empty states; text owns the state meaning. */
@Composable
fun ReceiptEmptyIllustration(modifier: Modifier = Modifier) {
    BrandArt(BrandArtKind.Box, modifier.size(width = 144.dp, height = 104.dp))
}
