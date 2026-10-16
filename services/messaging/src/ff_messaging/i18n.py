"""Arabic texts for API error codes (``error.message_ar``; ``error.message`` stays English)."""

from __future__ import annotations

ERRORS_AR: dict[str, str] = {
    "messaging_error": "تعذر تنفيذ الطلب",
    "bad_request": "طلب غير صالح",
    "validation_error": "فشل التحقق من صحة الطلب",
    "unauthenticated": "يلزم تسجيل الدخول",
    "forbidden": "غير مسموح لك بهذا الإجراء",
    "not_found": "غير موجود",
    "rate_limited": "محاولات كثيرة جداً، حاول بعد قليل",
    "limit_reached": "تم بلوغ الحد الأقصى",
    "unknown_frame": "إطار غير مدعوم",
    "http_error": "تعذر تنفيذ الطلب",
    "invalid_cursor": "مؤشر الصفحة غير صالح",
    "conversation_not_found": "المحادثة غير موجودة",
    "conversation_full": "المحادثة وصلت إلى الحد الأقصى من الرسائل",
    "conversation_limit_reached": "بلغت الحد الأقصى من المحادثات",
    "message_not_found": "الرسالة غير موجودة",
    "user_blocked": "ألغِ حظر هذا المستخدم أولاً",
    "cannot_block_self": "لا يمكنك حظر نفسك",
    "cannot_block_platform": "لا يمكن حظر هذا الحساب",
    "block_limit_reached": "قائمة الحظر ممتلئة",
    "duplicate_participant": "تكرر أحد المشاركين في القائمة",
    "conflicting_role": "الدور المحدد يتعارض مع دورك في المحادثة",
    "invalid_role": "دور المنصة مخصص لحسابات المنصة فقط",
    "not_enough_participants": "المحادثة تحتاج إلى مشاركَين مختلفَين على الأقل",
    "too_many_participants": "عدد المشاركين كبير جداً",
    "context_ref_required": "معرّف سياق المحادثة مطلوب",
    "invalid_attachment": "المرفق غير صالح",
    "attachment_url_not_allowed": "رابط المرفق غير مسموح",
    "attachment_type_not_allowed": "نوع المرفق غير مسموح",
    "attachment_too_large": "حجم المرفق كبير جداً",
    "too_many_attachments": "عدد المرفقات كبير جداً",
    "invalid_message": "الرسالة غير صالحة",
    "invalid_message_type": "لا يمكن للمستخدمين إرسال هذا النوع من الرسائل",
    "empty_message": "نص الرسالة لا يمكن أن يكون فارغاً",
    "message_rejected": "تم رفض الرسالة بسبب سياسة المحتوى",
    "title_too_long": "العنوان طويل جداً",
    "title_rejected": "تم رفض العنوان بسبب سياسة المحتوى",
    "text_too_long": "نص الرسالة طويل جداً",
}


def message_ar(code: str) -> str:
    return ERRORS_AR.get(code) or ERRORS_AR["http_error"]
