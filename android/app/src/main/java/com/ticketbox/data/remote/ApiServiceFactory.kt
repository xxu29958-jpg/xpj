package com.ticketbox.data.remote

import com.ticketbox.security.SessionCredentialRotator

interface ApiServiceFactory {
    fun create(baseUrl: String, tokenProvider: () -> String?): ApiService

    fun create(
        baseUrl: String,
        tokenProvider: () -> String?,
        ledgerIdProvider: () -> String?,
    ): ApiService = create(baseUrl, tokenProvider)
}

interface SessionAwareApiServiceFactory : ApiServiceFactory {
    fun create(baseUrl: String, credentials: SessionCredentialRotator): ApiService
}
