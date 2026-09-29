package com.ticketbox.data.repository

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.remote.dto.BillSplitAgreementDto

private val agreementReadAdapter = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
    .adapter(BillSplitAgreementDto::class.java)

/** Canonical facts use the existing Debt read owner; input-dependent previews never enter its cache. */
internal suspend fun DebtQueryReader.agreement(task: DebtTask): Result<ReadSnapshot<BillSplitAgreementDto>> =
    read(task.binding, DebtQueryScope(debtScope(task.binding, "debt_agreement", task.debtPublicId), task.debtPublicId),
        DebtReadSpec(agreementReadAdapter, { splitAgreement(task.debtPublicId, null) },
            validate = { value ->
                require(value.invitationPublicId.isNotBlank() && task.debtPublicId in value.debtPublicIds())
                validateDebt(value.originalDebt, task.binding, null, allowShell = true)
                value.returnDebt?.let { validateDebt(it, task.binding, null, allowShell = true) }
                require(value.originalDebt.sourceId == value.invitationPublicId &&
                    value.originalDebt.sourceType == "bill_split")
                require(value.returnDebt?.let { it.sourceId == value.invitationPublicId &&
                    it.sourceType == "bill_split_return" && it.publicId != value.originalDebt.publicId } != false)
            },
            isNewer = { old, incoming -> incoming.originalDebt.rowVersion > old.originalDebt.rowVersion ||
                (incoming.returnDebt?.rowVersion ?: 0) > (old.returnDebt?.rowVersion ?: 0) },
            project = { value, denied ->
                require(value.debtPublicIds().none { it in denied }) { "这段往来的读取已失效，请重新核对。" }
                value
            },
            publicIds = BillSplitAgreementDto::debtPublicIds))

internal fun BillSplitAgreementDto.debtPublicIds(): Set<String> =
    setOfNotNull(originalDebt.publicId, returnDebt?.publicId)
