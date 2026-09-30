package com.ticketbox.data.repository

/** Unrelated recovery fixtures must fail loudly if routed to repayment review. */
internal fun unusedRepaymentReviews(): RepaymentReviewActions = java.lang.reflect.Proxy.newProxyInstance(
    RepaymentReviewActions::class.java.classLoader, arrayOf(RepaymentReviewActions::class.java),
) { _, method, _ -> error("Unexpected repayment review call: ${method.name}") } as RepaymentReviewActions
