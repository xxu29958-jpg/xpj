package com.ticketbox.ui.screens.settings

import com.ticketbox.R
import kotlin.test.Test
import kotlin.test.assertEquals

class DataExportScreenModelTest {
    @Test
    fun scopeRowsKeepOfficialDataBeforeOfflineCopyAndExport() {
        val rows = dataExportScopeRows()

        assertEquals(
            listOf(
                DataExportScopeKind.Authority,
                DataExportScopeKind.OfflineCopy,
                DataExportScopeKind.ExportScope,
            ),
            rows.map { it.kind },
        )
        assertEquals(
            listOf(
                R.string.settings_data_export_authority_label,
                R.string.settings_data_export_cache_label,
                R.string.settings_data_export_export_label,
            ),
            rows.map { it.titleRes },
        )
    }
}
