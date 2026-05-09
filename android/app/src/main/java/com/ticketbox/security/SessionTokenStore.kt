package com.ticketbox.security

interface SessionTokenStore {
    fun saveToken(token: String)

    fun getToken(): String?

    fun clear()
}
