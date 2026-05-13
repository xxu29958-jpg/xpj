package com.ticketbox.data.repository

import kotlin.test.Test
import kotlin.test.assertEquals

class BackendErrorMessageMapperTest {
    @Test
    fun masksServerErrorDetailsForUsers() {
        val message = backendErrorUserMessage(
            errorCode = "server_error",
            serverMessage = "本地大模型识别失败：Connection refused at 127.0.0.1:11434",
        )

        assertEquals("暂时处理不了，请稍后再试。", message)
    }

    @Test
    fun mapsKnownBackendErrorCodesToGrayCopy() {
        assertEquals("绑定已失效，请重新绑定账本。", backendErrorUserMessage("invalid_token", "Token 无效。"))
        assertEquals("请使用新版绑定方式。", backendErrorUserMessage("legacy_auth_removed", "请使用新版绑定方式。"))
        assertEquals("账本版本过旧，请重启电脑上的小票夹后再试。", backendErrorUserMessage("route_not_found", "接口不存在。"))
        assertEquals("操作方式不正确，请更新 App 后再试。", backendErrorUserMessage("method_not_allowed", "请求方法不允许。"))
        assertEquals("当前角色为只读，无法修改账本。", backendErrorUserMessage("permission_denied", "当前角色无权进行此操作。"))
        assertEquals("固定支出不存在。", backendErrorUserMessage("recurring_item_not_found", "Not found"))
        assertEquals("固定支出已归档，不能继续修改。", backendErrorUserMessage("recurring_item_archived", "Archived"))
        assertEquals("通知来源暂不支持。", backendErrorUserMessage("notification_source_invalid", "Unsupported"))
    }

    @Test
    fun keepsUnknownBackendMessageAsFallback() {
        assertEquals("自定义错误。", backendErrorUserMessage("future_error", "自定义错误。"))
    }
}
