package com.ticketbox.data.remote.api

import com.ticketbox.data.remote.dto.DeviceRenameRequestDto
import com.ticketbox.data.remote.dto.MyDeviceDto
import com.ticketbox.data.remote.dto.MyDeviceListResponseDto
import com.ticketbox.data.remote.dto.PairingCodeCreateRequestDto
import com.ticketbox.data.remote.dto.PairingCodeResponseDto
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path

interface LedgerDeviceApi {
    // issue #65 slice 6b: owner "My Devices" (backend slice 6a; owner-only,
    // path-ledger-bound). list / rename / revoke + mint a pairing code to add a
    // device (the new device then pairs via the existing bind flow).
    @GET("api/ledgers/{ledgerId}/devices")
    suspend fun ledgerDevices(@Path("ledgerId") ledgerId: String): MyDeviceListResponseDto

    @POST("api/ledgers/{ledgerId}/devices/{publicId}/rename")
    suspend fun renameLedgerDevice(
        @Path("ledgerId") ledgerId: String,
        @Path("publicId") publicId: String,
        @Body request: DeviceRenameRequestDto,
    ): MyDeviceDto

    @POST("api/ledgers/{ledgerId}/devices/{publicId}/revoke")
    suspend fun revokeLedgerDevice(
        @Path("ledgerId") ledgerId: String,
        @Path("publicId") publicId: String,
    ): MyDeviceDto

    // 204 No Content; Retrofit's built-in Unit converter consumes the empty body.
    @POST("api/ledgers/{ledgerId}/devices/{publicId}/delete")
    suspend fun deleteLedgerDevice(
        @Path("ledgerId") ledgerId: String,
        @Path("publicId") publicId: String,
    )

    @POST("api/ledgers/{ledgerId}/devices/pairing-codes")
    suspend fun createLedgerDevicePairingCode(
        @Path("ledgerId") ledgerId: String,
        @Body request: PairingCodeCreateRequestDto,
    ): PairingCodeResponseDto
}
