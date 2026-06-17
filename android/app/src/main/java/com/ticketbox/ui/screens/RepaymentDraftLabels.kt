package com.ticketbox.ui.screens

import androidx.annotation.StringRes
import com.ticketbox.R
import com.ticketbox.domain.model.RepaymentDraftSource

/**
 * ADR-0049 §杠杆③ (slice 3a) — 还款捕获渠道 → 中文标签的单源映射（展示层不散写字面量）。
 *
 * 入参是服务端权威的 `RepaymentDraft.source` 原始 api 值（alipay / jd / meituan / wechat /
 * bank_sms / bank_app / other），与后端 `REPAYMENT_DRAFT_SOURCE_LABELS` 的键一一对应；未知值
 * 回落「其他还款」而非崩溃（前向兼容后端新增渠道）。
 */
@StringRes
fun repaymentDraftSourceLabelRes(source: String): Int = when (source) {
    RepaymentDraftSource.Alipay.apiValue -> R.string.repayment_draft_source_alipay
    RepaymentDraftSource.Jd.apiValue -> R.string.repayment_draft_source_jd
    RepaymentDraftSource.Meituan.apiValue -> R.string.repayment_draft_source_meituan
    RepaymentDraftSource.WeChat.apiValue -> R.string.repayment_draft_source_wechat
    RepaymentDraftSource.BankSms.apiValue -> R.string.repayment_draft_source_bank_sms
    RepaymentDraftSource.BankApp.apiValue -> R.string.repayment_draft_source_bank_app
    RepaymentDraftSource.Other.apiValue -> R.string.repayment_draft_source_other
    // 未知值(后端将来新增渠道)前向兼容,回落「其他还款」。
    else -> R.string.repayment_draft_source_other
}
