package com.ticketbox.data.repository

import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.ticketbox.data.remote.dto.ExpenseTimeInputDto

/** Retains the original saved command format, including the nested time_input field names. */
@JsonClass(generateAdapter = true)
internal data class MemberProposalWire(val amountCents: Long, val note: String?,
    val supersedesProposalPublicId: String? = null, val timeInput: ExpenseTimeInputDto? = null)

internal object MemberSettlementCommandJson {
    private val moshi = Moshi.Builder().build()
    private val proposal = moshi.adapter(MemberProposalWire::class.java)
    private val types = mapOf("propose" to MemberSettlementCommand.Propose::class.java,
        "confirm" to MemberSettlementCommand.Confirm::class.java, "withdraw" to MemberSettlementCommand.Withdraw::class.java,
        "reject" to MemberSettlementCommand.Reject::class.java, "forgive" to MemberSettlementCommand.Forgive::class.java)

    fun kind(command: MemberSettlementCommand): String = types.entries.single { it.value == command.javaClass }.key

    fun read(kind: String, json: String): MemberSettlementCommand = if (kind == "propose") {
        val wire = requireNotNull(proposal.fromJson(json))
        MemberSettlementCommand.Propose(wire.amountCents, wire.note, wire.supersedesProposalPublicId, wire.timeInput?.toDomain())
    } else requireNotNull(moshi.adapter(requireNotNull(types[kind])).fromJson(json))

    fun write(command: MemberSettlementCommand): String = if (command is MemberSettlementCommand.Propose) {
        proposal.toJson(MemberProposalWire(command.amountCents, command.note, command.supersedesProposalPublicId,
            command.timeInput?.toRequest()))
    } else moshi.adapter<MemberSettlementCommand>(command.javaClass).toJson(command)
}
