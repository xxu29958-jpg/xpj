package com.ticketbox.data.remote

import com.ticketbox.security.SessionTokenStore

interface ApiServiceFactory {
    fun create(baseUrl: String, tokenProvider: () -> String?): ApiService
}

interface SessionAwareApiServiceFactory : ApiServiceFactory {
    fun create(baseUrl: String, tokenStore: SessionTokenStore): ApiService
}
