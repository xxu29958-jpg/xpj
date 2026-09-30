package com.ticketbox.data.local

import androidx.room.Dao
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Transaction

/** Unsubmitted input, deliberately excluded from every projection/cache cleanup. */
@Entity(tableName = "expense_fact_inputs", primaryKeys = ["ownerKey", "ledgerId", "expenseId", "formKey"])
data class ExpenseFactInputEntity(
    val ownerKey: String,
    val ledgerId: String,
    val expenseId: Long,
    val formKey: String,
    val bindingJson: String,
    val originalKey: String,
    val inputJson: String,
)

@Dao
interface ExpenseFactInputDao {
    @Query("SELECT * FROM expense_fact_inputs WHERE ownerKey = :owner AND ledgerId = :ledger AND expenseId = :expense")
    suspend fun factInputs(owner: String, ledger: String, expense: Long): List<ExpenseFactInputEntity>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun putFactInput(input: ExpenseFactInputEntity)

    @Query("DELETE FROM expense_fact_inputs WHERE ownerKey = :owner AND ledgerId = :ledger AND expenseId = :expense AND formKey = :form")
    suspend fun deleteFactInput(owner: String, ledger: String, expense: Long, form: String)

    @Transaction
    suspend fun replaceFactInput(expected: ExpenseFactInputEntity?, input: ExpenseFactInputEntity) {
        check(factInputs(input.ownerKey, input.ledgerId, input.expenseId).singleOrNull { it.formKey == input.formKey } == expected) {
            "原输入已在另一处变化，请重新打开核对。"
        }
        putFactInput(input)
    }

    @Transaction
    suspend fun consumeFactInput(input: ExpenseFactInputEntity) {
        check(factInputs(input.ownerKey, input.ledgerId, input.expenseId).singleOrNull { it.formKey == input.formKey } == input) {
            "原输入已变化，尚未提交，请重新核对。"
        }
        deleteFactInput(input.ownerKey, input.ledgerId, input.expenseId, input.formKey)
    }
}
