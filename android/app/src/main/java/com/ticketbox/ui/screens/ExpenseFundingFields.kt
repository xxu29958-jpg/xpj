package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.text.input.KeyboardType
import com.ticketbox.data.remote.dto.FinancialAccountDto
import com.ticketbox.data.repository.FundsRepository
import com.ticketbox.data.repository.ExpenseFundingInput
import com.ticketbox.data.repository.fundingInputAdapter
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.design.AppSpacing
import kotlinx.coroutines.flow.collectLatest

internal val LocalFundsRepository = compositionLocalOf<FundsRepository?> { null }

private val fundingAdapter = fundingInputAdapter

@Composable
internal fun ExpenseFundingFields(json: String, currency: CurrencyCode, enabled: Boolean, refund: Boolean = false, change: (String) -> Unit) {
    val repository = LocalFundsRepository.current ?: return
    var accounts by remember { mutableStateOf<List<FinancialAccountDto>>(emptyList()) }
    var message by remember { mutableStateOf<String?>(null) }
    var choose by rememberSaveable { mutableStateOf(false) }
    var attempt by remember { mutableStateOf(0) }
    LaunchedEffect(repository, attempt) {
        repository.access().collectLatest { access ->
            accounts = emptyList()
            if (access != null) repository.accounts(access.binding).fold(
                onSuccess = { read -> accounts = read.value.filterNot { it.archived || !refund && it.creditKind == "one_off" }; message = if (read.fromCache) "显示上次读取的账户，保存时会核对版本。" else null },
                onFailure = { message = it.message })
        }
    }
    val parsed = remember(json) { runCatching { requireNotNull(fundingAdapter.fromJson(json)) } }
    val parts = parsed.getOrDefault(emptyList())
    val editable = enabled && parsed.isSuccess
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        Text(if (refund) "实际退款去向" else "付款来源（可选，支持分开付款）")
        message?.let { Text(it) }
        if (parsed.isFailure) Text("付款来源原稿无法读取，原输入仍保留。请返回重新打开，勿重复提交。")
        parts.forEachIndexed { index, row ->
            Text("${row.accountName} · ${row.accountCurrency}")
            fun put(next: ExpenseFundingInput) { change(fundingAdapter.toJson(parts.toMutableList().also { it[index] = next })) }
            OutlinedTextField(row.expenseAmount, { value -> put(row.copy(expenseAmount = value,
                accountAmount = if (row.accountCurrency == row.expenseCurrency) value else row.accountAmount)) },
                label = { Text("${if (refund) "原币退款组成" else "抵付消费"}（${row.expenseCurrency}）") }, enabled = editable, modifier = Modifier.fillMaxWidth(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), singleLine = true)
            if (row.accountCurrency != row.expenseCurrency) OutlinedTextField(row.accountAmount, { put(row.copy(accountAmount = it)) },
                label = { Text("${if (refund) "实际退入 / 抵扣" else "实际扣款 / 信用使用"}（${row.accountCurrency}）") }, enabled = editable, modifier = Modifier.fillMaxWidth(),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), singleLine = true)
            TextButton(onClick = { change(fundingAdapter.toJson(parts.filterIndexed { n, _ -> n != index })) }, enabled = editable) { Text("移除这项付款") }
            if (!refund) androidx.compose.foundation.layout.Row {
                androidx.compose.material3.Switch(row.includedInOpening, { put(row.copy(includedInOpening = it)) }, enabled = editable)
                Text("已纳入期初，不重复扣款")
            }
        }
        AppSecondaryButton(if (refund) "选择退入 / 抵扣账户" else "选择付款账户", enabled = editable && parts.size < 8) { choose = true }
        Text(if (refund) "信用账户抵扣欠款或保留溢缴款；其他账户记录实际到账。尚未到账时保留原稿。" else "未选择时只记录消费，付款来源待补。可在往来 → 资金账户添加账户。")
    }
    if (choose) AlertDialog(onDismissRequest = { choose = false }, title = { Text("实际付款来源") }, text = {
        LazyColumn {
            items(accounts, key = { it.publicId }) { row -> TextButton(onClick = {
                change(fundingAdapter.toJson(parts + ExpenseFundingInput(java.util.UUID.randomUUID().toString(), row.publicId,
                    row.rowVersion, row.name, row.currencyCode, currency.storageKey))); choose = false
            }) { Text("${row.name} · ${row.currencyCode}") } }
            if (accounts.isEmpty()) item { Text("还没有可用账户，请先到资金账户添加。") }
        }
    }, confirmButton = { TextButton(onClick = { attempt += 1 }) { Text("刷新账户") } },
        dismissButton = { TextButton(onClick = { choose = false }) { Text("返回") } })
}
