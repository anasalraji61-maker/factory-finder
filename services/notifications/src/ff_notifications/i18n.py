"""Arabic texts for API error codes (``error.message_ar``; ``error.message`` stays English)."""

from __future__ import annotations

ERRORS_AR: dict[str, str] = {
    "bad_request": "طلب غير صالح",
    "validation_error": "فشل التحقق من صحة الطلب",
    "unauthenticated": "يلزم تسجيل الدخول",
    "forbidden": "غير مسموح لك بهذا الإجراء",
    "not_found": "غير موجود",
    "too_many_requests": "طلبات كثيرة جداً، حاول لاحقاً",
    "conflict": "تعارض مع الحالة الحالية",
    "http_error": "تعذر تنفيذ الطلب",
    "invalid_watch": "حدد إما معرّف المنتج أو البحث، وليس كليهما",
    "invalid_threshold": "نسبة الانخفاض يجب أن تكون أكبر من 0 وحتى 100",
    "invalid_target": "السعر المستهدف يجب أن يكون موجباً",
    "invalid_money": "رقم أو عملة غير صالحة",
    "watchlist_full": "قائمة المتابعة ممتلئة",
    "watch_not_found": "عنصر المتابعة غير موجود",
    "alert_not_found": "التنبيه غير موجود",
    "device_limit": "بلغت الحد الأقصى من الأجهزة",
    "device_not_found": "الجهاز غير موجود",
    "invalid_prefs": "إعدادات الإشعارات غير صالحة",
    "send_limit": "طلبت رموز تحقق كثيرة، حاول لاحقاً",
    "locked": "محاولات خاطئة كثيرة، حاول لاحقاً",
    "no_pending": "لا يوجد بريد إلكتروني بانتظار التحقق",
    "code_expired": "انتهت صلاحية الرمز، اطلب رمزاً جديداً",
    "invalid_code": "رمز التحقق غير صحيح",
    "email_disabled": "إرسال البريد الإلكتروني غير مفعّل",
}


def message_ar(code: str) -> str:
    return ERRORS_AR.get(code) or ERRORS_AR["http_error"]
