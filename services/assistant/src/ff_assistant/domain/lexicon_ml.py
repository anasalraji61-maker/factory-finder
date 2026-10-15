"""Raw (unfolded) multilingual lexicon additions: Turkish, Kurdish (Sorani), Persian, simple Chinese.

Plain data only (no imports from matching/text) so the Han segmenter can read it without cycles.
``lexicon.py`` folds these into the same closed-class sets as the Arabic/English entries.
Turkish suffixes after an apostrophe (Basra'ya, Çin'den) are rewritten to markers by ``text.clean_text``.
Chinese has no spaces: ``han.segment`` splits it using every Han term found below and in ``aliases_ml.json``.
"""

from __future__ import annotations

RAW: dict[str, tuple[str, ...]] = {
    "TO": ("kadar", "icin", "için", "بۆ", "بو", "به", "تا", "到", "运到", "发到", "送到", "寄到", "至"),
    "FROM": ("از", "لەلایەن", "从", "来自", "自"),
    "IN": ("لە", "له", "در", "在"),
    "TRACK": (
        "takip", "takibi", "izle", "izleme", "nerede", "nerde", "konumu",
        "ردیابی", "پیگیری", "کجاست", "کجا", "بەدواداچوون", "شوێنکەوتن", "لەکوێیە", "کوێیە", "کوێ",
        "追踪", "跟踪", "在哪里", "在哪", "哪里", "到哪了",
    ),
    "TRUST": (
        "guvenilir", "güvenilir", "güvenilirlik", "dolandirici", "dolandırıcı", "sahtekar", "itibar", "guvenli", "güvenli",
        "معتبر", "اعتماد", "کلاهبردار", "تقلبی", "امن",
        "متمانە", "متمانەپێکراو", "باوەڕپێکراو", "فێڵباز", "ساختە", "متمانه",
        "可靠", "靠谱", "信誉", "可信", "骗子", "诈骗", "诚信",
    ),
    "SHIP": (
        "nakliye", "navlun", "kargo", "tasima", "taşıma", "gonderim", "gönderim", "gümrük", "gumruk", "teslimat", "sevkiyat",
        "حمل", "باربری", "ارسال", "گمرک", "گمرکی", "باربري",
        "گواستنەوە", "گواستنەوەی", "گەیاندن", "گەیاندنی", "گەیاندنەوە", "ناردن", "ناردنی", "گومرگ", "بارهەڵگرتن", "کرێی",
        "运费", "海运", "空运", "物流", "运输", "清关", "运", "发货",
    ),
    "COST": (
        "kadar", "kac", "kaç", "maliyet", "maliyeti", "fiyat", "fiyati", "fiyatı", "ucret", "ücret", "ücreti", "tutar", "masraf",
        "هزینه", "قیمت", "چقدر", "کرایه", "هزينه",
        "نرخ", "نرخی", "بەهای", "چەندە", "تێچوو", "تێچووی", "بها", "نرخەکەی",
        "多少钱", "要多少钱", "多少", "费用", "价格", "成本", "报价", "价钱", "总成本", "运费", "到岸价", "落地价",
    ),
    "HELP": ("merhaba", "selam", "yardim", "yardım", "سلام", "کمک", "ساڵاو", "سلاو", "چۆنی", "چۆنیت", "یارمەتی", "你好", "您好", "帮助", "帮忙", "谢谢"),
    "USED": ("kullanilmis", "kullanılmış", "ikinci", "کارکرده", "دوم", "بەکارهاتوو", "دووەم", "二手", "旧"),
    "NEW": ("yeni", "نو", "تازه", "نوێ", "全新", "新"),
    "REFURB": ("yenilenmis", "yenilenmiş", "بازسازی", "نوێکراوە", "翻新"),
    "MAX": ("altinda", "altında", "کمتر", "زیر", "حداکثر", "کەمتر", "لەژێر", "以下", "不超过", "低于"),
    "MIN": ("ustunde", "üstünde", "uzeri", "üzeri", "بیشتر", "بالای", "زیاتر", "سەروو", "以上", "高于"),
    "BUDGET": ("butce", "bütçe", "بودجه", "بودجە", "预算"),
    "STATUS": (
        "durum", "durumu", "varis", "varış", "ne", "zaman", "nerede", "nerde", "کجاست", "کجا", "کوێیە", "کوێ", "在哪里", "在哪", "哪里",
        "وضعیت", "کی", "رسیدن", "چەند", "کەی", "حاڵەت",
        "状态", "几时", "什么时候", "到港",
    ),
    "STOP": (
        "سلاو", "چۆنی", "چۆنیت",
        "ne", "istiyorum", "istiyoruz", "lazim", "lazım", "ariyorum", "arıyorum", "almak", "alacagim", "bana", "ile", "ve", "bir", "bu",
        "nereden", "bul", "var", "mi", "mı", "mu", "mü", "hangi", "nasil", "olarak", "teslim", "lutfen", "lütfen", "ben", "el",
        "میخواهم", "می", "خواهم", "میخوام", "لازم", "نیاز", "دارم", "برای", "را", "که", "یک", "این", "آن", "چه", "ممکن", "است", "هست", "باید",
        "دەمەوێت", "دەمەوێ", "دەوێت", "دەوێ", "تەواوی", "ئەمەوێت", "پێویستمە", "دەمەوێتەوە", "ئەم", "ئەو", "ئایا", "دەکرێت", "هەیە", "بکڕم", "بکرم", "ڕێکەوتن",
        "我想买", "我想", "我要", "我需要", "想买", "想", "要", "需要", "求购", "采购", "购买", "买", "找", "有没有", "请", "帮我", "的", "了", "吗",
        "呢", "啊", "一下", "能", "可以", "你们", "把", "给", "我的", "我", "这个", "这", "那", "是", "怎么", "如何", "什么", "要多少", "吨的",
    ),
    "HS_NOISE": (
        "gtip", "kodu", "vergisi", "tarife", "oranı", "orani", "nedir", "ne",
        "کد", "تعرفه", "عوارض", "حقوق", "چیست", "چيست", "چنده",
        "کۆد", "باج", "تەعریفە", "چییە", "چیە",
        "海关", "编码", "税号", "关税", "税率", "是", "什么", "多少",
    ),
    "RFQ_NOISE": (
        "teklif", "talep", "olustur", "oluştur", "iste", "topla", "satin", "satın", "alma", "talebi", "rfq",
        "درخواست", "خرید", "استعلام", "ثبت", "پیشنهاد", "دریافت",
        "داواکاری", "کڕین", "پێشنیار", "وەربگرە", "بڵاوکردنەوە",
        "发布", "询价", "求购单", "采购需求", "收集报价", "创建", "报价", "需求",
    ),
    # multi-character units (single tokens after segmentation)
    "UNIT_TON": ("tonluk", "تن", "تەن", "吨", "公吨"),
    "UNIT_KG": ("kilo", "kilogram", "کیلو", "کیلوگرم", "کیلۆ", "کیلۆگرام", "公斤", "千克"),
    "UNIT_PIECE": ("adet", "parça", "parca", "عدد", "دانه", "دانە", "个", "件", "台", "套", "只", "张", "条"),
    "UNIT_CONTAINER": ("konteyner", "کانتینر", "کۆنتەینەر", "集装箱", "柜", "货柜"),
    "UNIT_METER": ("metre", "متر", "米"),
    "UNIT_LITER": ("litre", "لیتر", "لیتەر", "升"),
    "CUR_USD": ("dolar", "دلار", "دۆلار", "美元", "美金"),
    "CUR_IQD": ("dinar", "دینار", "第纳尔"),
    "CUR_CNY": ("元", "人民币"),
    "KIND_LINE": (
        "üretim hattı", "uretim hatti", "üretim hatları", "komple tesis",
        "خط تولید", "خطوط تولید", "کارخانه کامل",
        "هێڵی بەرهەمهێنان", "هێڵی به‌رهەم‌هێنان", "هێڵی بەرهەم", "کارگەی تەواو",
        "生产线", "流水线", "整套工厂",
    ),
    "KIND_RAW": (
        "hammadde", "ham madde", "hammaddeler",
        "مواد اولیه", "مواد خام", "ماده اولیه",
        "کەرەستەی خاو", "ماددەی خاو", "مادەی خاو",
        "原材料", "原料",
    ),
    # regex fragments (matched on folded text; Han terms tolerate inserted spaces)
    "HS_RE": (
        "gtip", "gumruk vergisi", "gumruk tarife", "hs kodu", "gumruk orani", "ithalat vergisi", "gumruk kodu",
        "کد تعرفه", "تعرفه گمرکی", "عوارض گمرکی", "حقوق گمرکی", "کد hs", "کد گمرکی", "تعرفه",
        "کۆدی گومرگی", "باجی گومرگی", "کۆدی hs", "باجی هاوردە", "تەعریفەی گومرگی", "کۆدی hs",
        "海关编码", "税号", "关税", "税率", "hs编码", "海关代码",
    ),
    "DOOR_RE": (
        "kapiya kadar", "kapi teslim", "toplam maliyet", "tam maliyet", "toplam fiyat",
        "تا درب", "درب به درب", "هزینه کل", "هزینه تمام شده", "قیمت تمام شده",
        "تا دەرگا", "تا دەرگای", "تێچووی تەواو", "تێچووی گشتی", "نرخی تەواو",
        "门到门", "到门", "到岸价", "总成本", "全部费用", "落地价",
    ),
    "OFFTOPIC_RE": (
        "hava durumu", "siir", "fikra", "futbol", "yemek tarifi", "burc", "haberler", "bitcoin",
        "آب و هوا", "جوک", "فوتبال", "طالع بینی", "دستور پخت",
        "کەش و هەوا", "گاڵتە", "تۆپی پێ", "شیعر", "ڕسپی",
        "天气", "笑话", "足球", "新闻", "比特币", "食谱", "写诗", "诗",
    ),
    "MESSAGE_RE": (
        "ozel mesaj", "mesaj gonder", "mesaj at", "whatsapp", "telegram", "wechat",
        "tedarikci\\w* mesaj", "mesaj\\w*[^.?!]{0,30}(?:tedarikci|uretici|satici|fabrika)", "tedarikci\\w* (?:yaz|gonder|ilet)",
        "پیام خصوصی", "پیام شخصی", "پیام بفرست", "واتساپ", "واتس اپ", "تلگرام", "پیام[^.?!؟]{0,30}(?:تامین|فروشنده|کارخانه)",
        "به (?:تامین|فروشنده)[^.?!؟]{0,30}(?:پیام|بنویس)",
        "نامەی تایبەت", "نامەیەکی تایبەت", "نامە بنێرە", "پەیام بنێرە", "نامە[^.?!؟]{0,30}(?:دابینکەر|فرۆشیار|کارگە)",
        "پەیام[^.?!؟]{0,30}(?:دابینکەر|فرۆشیار|کارگە)", "واتساپ", "تێلێگرام",
        "私信", "私聊", "微信", "发(?:个)?(?:消息|信息|邮件|短信)", "给[^.?!。]{0,6}供应商[^.?!。]{0,4}(?:发|写|留言)",
        "(?:消息|信息|邮件)[^.?!。]{0,12}供应商", "联系[^.?!。]{0,4}(?:供应商|厂家|卖家)", "私下",
    ),
    "RFQ_RE": (
        "teklif iste", "teklif topla", "talep olustur", "satin alma talebi", "teklif talebi", "rfq",
        "درخواست خرید", "استعلام قیمت", "ثبت درخواست", "پیشنهاد دریافت", "دریافت پیشنهاد", "rfq",
        "داواکاری کڕین", "داواکاری نرخ", "داواکاری ببڵاوبکەوە", "پێشنیار وەربگرە", "داواکارییەک دروست", "rfq",
        "发布采购", "发布求购", "询价", "求购单", "采购需求", "收集报价", "创建询价", "发布需求",
    ),
}
