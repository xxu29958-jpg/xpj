package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import java.io.File
import kotlin.reflect.KClass
import kotlin.reflect.full.primaryConstructor
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

/**
 * ADR-0043 review follow-up — generative round-trip contract gate.
 *
 * The hand-written `*DtoContractTest` fixtures encode "the shape a developer THOUGHT
 * the server sends" — which is exactly how the flat-vs-nested `ErrorDto` drift could
 * survive until a human review caught it ([[feedback_occ_test_token_from_rendered_carrier]]).
 * This gate instead drives each DTO from the backend's committed OpenAPI snapshot
 * (`docs/architecture/openapi_contract.json`):
 *
 *  1. **Name parity** — every `@Json` wire name on the DTO must be a property of its
 *     backend schema. A backend rename/drop leaves an orphan field here → CI red.
 *     The live hazard is `ExpenseDto`'s FX surface (`fx_rate` / `exchange_rate_*` /
 *     `original_amount*`): all nullable-with-default, so today a backend rename just
 *     degrades to a silent `null` and no hand-written test reddens.
 *  2. **Generative round-trip** — synthesize a typed instance FROM the schema and
 *     decode it through the REAL production Moshi (`KotlinJsonAdapterFactory`, the
 *     same builder `ApiClient` uses). A backend type change → Moshi decode throws.
 *
 * The mapping is explicit because Android `XxxDto` ↔ backend `XxxResponse` is NOT 1:1
 * by name (no shared registry). Grow [pairs] as more DTOs are brought under the gate.
 */
class OpenApiContractGateTest {

    private data class Pairing(val dto: KClass<*>, val schema: String)

    private val pairs = listOf(
        Pairing(ErrorDto::class, "ErrorResponse"),
        Pairing(ExpenseDto::class, "ExpenseResponse"),
        Pairing(IncomePlanDto::class, "IncomePlanResponse"),
        Pairing(IncomePlanListResponseDto::class, "IncomePlanListResponse"),
        Pairing(IncomePlanCreateRequestDto::class, "IncomePlanCreateRequest"),
        Pairing(IncomePlanUpdateRequestDto::class, "IncomePlanUpdateRequest"),
        Pairing(IncomePlanTokenRequestDto::class, "IncomePlanTokenRequest"),
        Pairing(BillSplitInviteRequestDto::class, "BillSplitInviteRequest"),
        Pairing(BillSplitAcceptRequestDto::class, "BillSplitAcceptRequest"),
        Pairing(BillSplitSentDto::class, "BillSplitSentResponse"),
        Pairing(BillSplitInboxDto::class, "BillSplitInboxResponse"),
        Pairing(BillSplitSentListResponseDto::class, "BillSplitSentListResponse"),
        Pairing(BillSplitInboxListResponseDto::class, "BillSplitInboxListResponse"),
        Pairing(DiscretionaryResponseDto::class, "DiscretionaryResponse"),
        Pairing(BudgetAdviseRequestDto::class, "BudgetAdviseRequest"),
        Pairing(BudgetSuggestionDto::class, "BudgetSuggestionDto"),
        Pairing(BudgetAdviceDto::class, "BudgetAdviceDto"),
        Pairing(BudgetAdviseResponseDto::class, "BudgetAdviseResponse"),
        Pairing(RecurringCandidateItemDto::class, "RecurringCandidateItem"),
        Pairing(RecurringCandidatesResponseDto::class, "RecurringCandidatesResponse"),
        Pairing(DataQualitySummaryDto::class, "DataQualitySummaryResponse"),
        Pairing(UserUiPreferencesDto::class, "UserUiPreferencesResponse"),
        Pairing(UserUiPreferencesUpdateRequestDto::class, "UserUiPreferencesUpdateRequest"),
        Pairing(TagListItemDto::class, "TagListItem"),
        Pairing(TagManagementListDto::class, "TagManagementListResponse"),
        Pairing(TagDetailDto::class, "TagDetailResponse"),
        Pairing(TagMutationDto::class, "TagMutationResponse"),
        Pairing(TagUndoDto::class, "TagUndoResponse"),
    )

    @Test
    fun everyDtoFieldIsBackedByItsOpenApiSchema() {
        val drift = pairs.mapNotNull { p ->
            val orphans = dtoJsonNames(p.dto) - schemaProperties(p.schema)
            if (orphans.isEmpty()) {
                null
            } else {
                "${p.dto.simpleName} → ${p.schema}: @Json fields absent from the backend schema " +
                    "(a backend rename/drop the DTO didn't track): ${orphans.sorted()}"
            }
        }
        assertTrue(
            drift.isEmpty(),
            "Android DTO ↔ OpenAPI contract drift — regenerate the DTO or the snapshot:\n" +
                drift.joinToString("\n"),
        )
    }

    @Test
    fun eachDtoDecodesASyntheticBackendInstance() {
        for (p in pairs) {
            val json = ANY.toJson(synthesizeSchema(p.schema, mutableSetOf()))
            val decoded = MOSHI.adapter(p.dto.java).fromJson(json)
            assertNotNull(
                decoded,
                "${p.dto.simpleName}: production Moshi could not decode a synthesized ${p.schema}.\n$json",
            )
        }
    }

    @Test
    fun parityCheckRedsOnASimulatedBackendRename() {
        // Self-test the orphan detection: prove it reddens when the backend renames a
        // field the DTO still references (the exact failure mode this gate exists for),
        // and stays green when the names align — so a green run above is meaningful.
        val dtoNames = dtoJsonNames(TagDetailDto::class) // public_id, name, row_version
        assertEquals(setOf("row_version"), dtoNames - setOf("public_id", "name", "row_version_renamed"))
        assertTrue((dtoNames - setOf("public_id", "name", "row_version")).isEmpty())
    }

    // ── reflection: the DTO's wire names (@param:Json name, else the property name) ──
    private fun dtoJsonNames(dto: KClass<*>): Set<String> {
        val ctor = dto.primaryConstructor ?: error("${dto.simpleName} has no primary constructor")
        return ctor.parameters.map { param ->
            param.annotations.filterIsInstance<Json>().firstOrNull()?.name ?: param.name!!
        }.toSet()
    }

    @Suppress("UNCHECKED_CAST")
    private fun schemaProperties(name: String): Set<String> {
        val schema = SCHEMAS[name] as? Map<String, Any?>
            ?: error("schema '$name' missing from the OpenAPI snapshot — fix the mapping in `pairs`")
        return (schema["properties"] as? Map<String, Any?>)?.keys.orEmpty()
    }

    // ── generative synthesis: a minimal typed instance from a schema's declared types ──
    @Suppress("UNCHECKED_CAST")
    private fun synthesizeSchema(schemaName: String, seen: MutableSet<String>): Map<String, Any?> {
        val schema = SCHEMAS[schemaName] as? Map<String, Any?> ?: error("schema '$schemaName' missing")
        val props = schema["properties"] as? Map<String, Any?> ?: return emptyMap()
        return props.mapValues { (_, raw) -> synthesizeValue(raw as Map<String, Any?>, seen) }
    }

    @Suppress("UNCHECKED_CAST")
    private fun synthesizeValue(node: Map<String, Any?>, seen: MutableSet<String>): Any? {
        (node["\$ref"] as? String)?.let { ref ->
            val name = ref.substringAfterLast('/')
            if (!seen.add(name)) return null // cycle guard
            return synthesizeSchema(name, seen).also { seen.remove(name) }
        }
        (node["anyOf"] as? List<Map<String, Any?>>)?.let { options ->
            val nonNull = options.filter { (it["type"] as? String) != "null" }
            val pick = nonNull.firstOrNull() ?: return null
            // Bound the synthesis: a nullable nested object/$ref → emit null rather than
            // recursing (the scalar fields, where the FX rename hazard lives, are exercised).
            val objectLike = pick.containsKey("\$ref") || (pick["type"] as? String) == "object"
            val nullable = options.any { (it["type"] as? String) == "null" }
            return if (objectLike && nullable) null else synthesizeValue(pick, seen)
        }
        return when (node["type"] as? String) {
            "string" -> when (node["format"] as? String) {
                "date" -> "2026-01-01"
                "date-time" -> "2026-01-01T00:00:00Z"
                else -> "x"
            }
            "integer" -> 1
            "number" -> 1.5
            "boolean" -> true
            "array" -> emptyList<Any?>()
            "object" -> emptyMap<String, Any?>()
            else -> null
        }
    }

    private companion object {
        // The SAME builder ApiClient/NetworkErrorHandler use in production (plain
        // reflection, no custom adapters), so the round-trip is faithful to runtime.
        val MOSHI: Moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
        val ANY = MOSHI.adapter(Any::class.java)

        @Suppress("UNCHECKED_CAST")
        val SCHEMAS: Map<String, Any?> = run {
            val root = ANY.fromJson(locateOpenApiSnapshot().readText()) as Map<String, Any?>
            (root["components"] as Map<String, Any?>)["schemas"] as Map<String, Any?>
        }

        private fun locateOpenApiSnapshot(): File {
            // JVM unit tests run with a module-relative working dir; walk up to the repo
            // root that holds the snapshot. Fail loud (never skip) so the gate can't no-op.
            var dir: File? = File(System.getProperty("user.dir") ?: ".").absoluteFile
            while (dir != null) {
                val candidate = File(dir, "docs/architecture/openapi_contract.json")
                if (candidate.exists()) return candidate
                dir = dir.parentFile
            }
            error("openapi_contract.json not found walking up from ${System.getProperty("user.dir")}")
        }
    }
}
