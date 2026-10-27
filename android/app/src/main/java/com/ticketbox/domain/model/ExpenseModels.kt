package com.ticketbox.domain.model

data class ManualExpenseSubmission(
    val originalCurrency: String? = null,
    val originalAmount: String? = null,
    val spentAt: String? = null,
    val merchant: String?,
    val category: String?,
    val categoryChoice: String? = null,
    val note: String?,
    val expenseTime: String?,
    val tags: String?,
    val valueScore: Int?,
    val regretScore: Int?,
    
    
    
    
    val clientRef: String? = null,
    val homeCurrencyCode: String? = null,
    val timeInput: ExpenseTimeInput? = null,
    val funding: List<ExpenseFunding>? = null,
)
