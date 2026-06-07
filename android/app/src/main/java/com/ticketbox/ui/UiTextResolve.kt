package com.ticketbox.ui

import android.content.Context
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.domain.model.UiText

/**
 * ADR-0044 (纯 ②): resolve a [UiText] to a display string. These UI-layer
 * extensions are the ONLY place a [UiText.Res] becomes Chinese text, keeping copy
 * resolution out of the domain / VM layer (translation-ready).
 */
@Composable
fun UiText.asString(): String = when (this) {
    is UiText.Res -> if (args.isEmpty()) {
        stringResource(id)
    } else {
        stringResource(id, *args.toTypedArray())
    }
    is UiText.Raw -> text
}

/** Non-composable resolution, for callers that already hold a [Context]
 *  (e.g. a snackbar/Toast raised outside composition). */
fun UiText.resolve(context: Context): String = when (this) {
    is UiText.Res -> if (args.isEmpty()) {
        context.getString(id)
    } else {
        context.getString(id, *args.toTypedArray())
    }
    is UiText.Raw -> text
}
