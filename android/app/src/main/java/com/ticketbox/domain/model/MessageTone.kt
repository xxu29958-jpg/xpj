package com.ticketbox.domain.model

/**
 * The semantic intent of a transient settings-tree status message — the
 * data-layer counterpart of /web `.dt-alert` variants. ViewModels tag their
 * `message` with a tone (success / failure / informational) so the presentation
 * layer can pick the right [com.ticketbox.ui.design.StateTone] without the VM
 * importing Compose or color tokens (§1 layering).
 *
 * Plain data (no Compose / color dependency) so it is safe to hold in VM state.
 * [Neutral] is the default for "no opinion" / cleared messages.
 */
enum class MessageTone {
    Success,
    Danger,
    Info,
    Neutral,
}
