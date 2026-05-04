package com.ticketbox

import android.os.Bundle
import androidx.activity.compose.setContent
import androidx.fragment.app.FragmentActivity
import com.ticketbox.security.BiometricAuthManager
import com.ticketbox.ui.navigation.TicketboxApp
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.appViewModelFactory
import com.ticketbox.viewmodel.settingsViewModelFactory

class MainActivity : FragmentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val container = (application as TicketboxApplication).container
        val biometricAuthManager = BiometricAuthManager(this)

        setContent {
            TicketboxTheme {
                TicketboxApp(
                    repository = container.expenseRepository,
                    appViewModelFactory = appViewModelFactory(
                        repository = container.expenseRepository,
                        settingsStore = container.settingsStore,
                        tokenStore = container.tokenStore,
                    ),
                    settingsViewModelFactory = settingsViewModelFactory(
                        repository = container.expenseRepository,
                        settingsStore = container.settingsStore,
                    ),
                    biometricAuthManager = biometricAuthManager,
                )
            }
        }
    }
}
