package com.ticketbox.domain.model

import androidx.annotation.StringRes

/**
 * ADR-0044 (纯 ②): a deferred user-facing string. ViewModels/repositories hold a
 * `UiText` in state instead of a resolved Chinese `String`, so resolution happens
 * in the presentation layer (`UiText.asString()` / `UiText.resolve(Context)`, both
 * in `com.ticketbox.ui.UiTextResolve`) — keeping UI copy out of the data/VM layer
 * (§1) and making it translation-ready.
 *
 * This is plain data (no Compose / Context / Android dependency) so it is
 * unit-testable and safe to hold in VM state; the `@StringRes` id is just an Int.
 * `Raw` carries an already-resolved string (e.g. a server passthrough message or a
 * value with no resource).
 */
sealed interface UiText {
    data class Res(@StringRes val id: Int, val args: List<Any> = emptyList()) : UiText

    data class Raw(val text: String) : UiText

    companion object {
        fun res(@StringRes id: Int, vararg args: Any): UiText = Res(id, args.toList())
        fun raw(text: String): UiText = Raw(text)
    }
}
