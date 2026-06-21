package com.ticketbox.domain

import java.io.File
import kotlin.test.Test
import kotlin.test.assertTrue

/**
 * issue #64 A2 guard: the domain layer must NOT depend on Compose.
 *
 * A2 cuts list-item recomposition via the Compose compiler's stability config
 * (app/compose_stability_config.conf) precisely so we never put @Stable /
 * @Immutable — which would pull androidx.compose.runtime into domain/model — on
 * the data classes. This test reddens if anyone reintroduces a Compose import
 * into domain/, keeping the stability promise external and the layer
 * (ENGINEERING_RULES §1: domain must not depend on upper layers) clean. Mirrors
 * OpenApiContractGateTest's walk-up file locate and fails loud (never skips).
 */
class DomainComposeImportGuardTest {

    @Test
    fun domainHasNoComposeImports() {
        val domainDir = locateDomainDir()
        val offenders = domainDir.walkTopDown()
            .filter { it.isFile && it.extension == "kt" }
            .flatMap { file ->
                file.readLines()
                    .filter { it.trimStart().startsWith("import androidx.compose") }
                    .map { "${file.name}: ${it.trim()}" }
            }
            .toList()
        assertTrue(
            offenders.isEmpty(),
            "domain/ must not import Compose (issue #64 A2: keep stability in " +
                "app/compose_stability_config.conf, not @Stable/@Immutable). Found:\n" +
                offenders.joinToString("\n"),
        )
    }

    private fun locateDomainDir(): File {
        val relative = "src/main/java/com/ticketbox/domain"
        var dir: File? = File(System.getProperty("user.dir") ?: ".").absoluteFile
        while (dir != null) {
            for (base in listOf(File(dir, relative), File(dir, "app/$relative"))) {
                if (base.isDirectory) return base
            }
            dir = dir.parentFile
        }
        error("domain/ dir not found walking up from ${System.getProperty("user.dir")}")
    }
}
