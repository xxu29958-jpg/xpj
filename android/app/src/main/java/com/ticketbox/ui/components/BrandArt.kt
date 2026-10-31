package com.ticketbox.ui.components

import androidx.compose.foundation.Image
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.clearAndSetSemantics
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.design.LocalAppSkin

/** The two 票根 illustrations (docs/design_reference/brand-icon/render_art.py). */
enum class BrandArtKind {
    /** Two stubs, the mark without its plate: capture and connect moments. */
    Pair,

    /** 票盒: stubs filed upright, the newest pulled up: genuine empty states. */
    Box,
}

internal fun brandArtRes(kind: BrandArtKind, skin: AppSkin): Int = when (kind) {
    BrandArtKind.Pair -> when (skin) {
        AppSkin.Paper -> R.drawable.art_stub_pair_paper
        AppSkin.Midnight -> R.drawable.art_stub_pair_midnight
    }
    BrandArtKind.Box -> when (skin) {
        AppSkin.Paper -> R.drawable.art_stub_box_paper
        AppSkin.Midnight -> R.drawable.art_stub_box_midnight
    }
}

/** Decorative only: hidden from accessibility; the surrounding text owns the meaning. */
@Composable
fun BrandArt(kind: BrandArtKind, modifier: Modifier = Modifier) {
    Image(
        painter = painterResource(brandArtRes(kind, LocalAppSkin.current)),
        contentDescription = null,
        modifier = modifier.clearAndSetSemantics {},
    )
}
