package com.ticketbox.domain.model

internal data class FamilyInvitationLink(
    val inviteToken: String,
    val serverUrl: String,
    val browserUrl: String,
    val hostLabel: String,
)

/** Strictly recognizes the browser invitation shape produced by Ticketbox. */
internal fun parseFamilyInvitationLink(raw: String): FamilyInvitationLink? {
    val candidate = raw.trim()
    val uri = runCatching { java.net.URI(candidate) }.getOrNull() ?: return null
    if (!uri.scheme.equals("https", ignoreCase = true)) return null
    if (uri.rawUserInfo != null || uri.rawQuery != null || uri.rawPath != "/web/auth/join") return null
    val host = uri.host?.takeIf { it.isNotBlank() } ?: return null
    val rawFragment = uri.rawFragment ?: return null
    if (!rawFragment.startsWith("invite=") || rawFragment.indexOf('&') >= 0) return null
    val token = parseFamilyInvitationToken(rawFragment.removePrefix("invite=")) ?: return null
    val authority = uri.rawAuthority ?: return null
    return FamilyInvitationLink(
        inviteToken = token,
        serverUrl = "https://$authority",
        browserUrl = candidate,
        hostLabel = host,
    )
}

/** Recognizes the one-shot plaintext shape emitted when no public invitation URL is configured. */
internal fun parseFamilyInvitationToken(raw: String): String? {
    val candidate = raw.trim()
    if (!candidate.startsWith(INVITATION_TOKEN_PREFIX) || candidate.length > INVITATION_TOKEN_MAX) return null
    return candidate.takeIf { token ->
        token.length > INVITATION_TOKEN_PREFIX.length &&
            token.drop(INVITATION_TOKEN_PREFIX.length).all { it.isLetterOrDigit() || it == '_' || it == '-' }
    }
}

private const val INVITATION_TOKEN_PREFIX = "inv_"
private const val INVITATION_TOKEN_MAX = 128

