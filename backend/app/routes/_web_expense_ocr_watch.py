"""Small read-only OCR status affordance beside the existing pending draft."""

from app.errors import AppError
from app.routes._web_session_common import resolve_web_actor_account_id
from app.services.background_task_response import task_response_dicts
from app.services.expense_ocr_task_service import latest_expense_ocr_task

OCR_TASK_MESSAGES = {
    "queued": "原件识别已排队，可以继续填写；识别不会覆盖你随后保存的修改。",
    "running": "正在识别原件，可以继续填写；识别不会覆盖你随后保存的修改。",
    "updated": "识别结果已更新，请核对建议。之前未保存的填写仍保留。",
    "no_result": "识别完成，未找到可用字段；可以手动填写。",
    "not_pending": "账单已离开待确认队列。",
    "conflict": "你后来保存的修改已保留，识别结果未覆盖账单。",
    "cancelled": "这次识别已取消，原件和填写仍保留。",
    "failed": "这次识别未完成，原件和填写仍保留；可以重新识别或手动填写。",
}


def expense_ocr_watch_context(db, request, *, tenant_id: str, expense_id: int) -> dict:
    try:
        account_id = resolve_web_actor_account_id(db, request, tenant_id)
    except AppError:
        return {}
    task = latest_expense_ocr_task(db, tenant_id=tenant_id, expense_id=expense_id, account_id=account_id)
    if task is None:
        return {}
    view = task_response_dicts(db, [task], tenant_id=tenant_id)[0]
    state = (view["result_summary"] or {}).get("outcome") if task.status == "completed" else task.status
    return {"ocr_task_watch": view, "ocr_task_message": OCR_TASK_MESSAGES.get(state, OCR_TASK_MESSAGES["failed"]),
            "ocr_task_messages": OCR_TASK_MESSAGES}
