final Map<String, Map<String, String>> coreStrings = _build();

Map<String, Map<String, String>> _build() {
  final ar = <String, String>{};
  final en = <String, String>{};
  _pairs.forEach((key, value) {
    ar[key] = value.$1;
    en[key] = value.$2;
  });
  return {'ar': ar, 'en': en};
}

// key: (arabic, english)
const Map<String, (String, String)> _pairs = {
  'app.name': ('مُوَرِّد', 'Factory Finder'),
  'nav.discover': ('استكشف', 'Discover'),
  'nav.requests': ('الطلبات', 'Requests'),
  'nav.messages': ('الرسائل', 'Messages'),
  'nav.logistics': ('الشحن', 'Logistics'),
  'nav.profile': ('حسابي', 'Profile'),
  'common.coming_soon': ('قريباً', 'Coming soon'),
  'common.coming_soon_msg': ('نعمل على تجهيز هذه الميزة وستكون متاحة قريباً.', 'We are working on this feature. It will be available soon.'),
  'common.retry': ('إعادة المحاولة', 'Retry'),
  'common.error': ('حدث خطأ غير متوقع', 'Something went wrong'),
  'common.cancel': ('إلغاء', 'Cancel'),
  'common.save': ('حفظ', 'Save'),
  'common.apply': ('تطبيق', 'Apply'),
  'common.reset': ('إعادة ضبط', 'Reset'),
  'common.all': ('الكل', 'All'),
  'common.estimate': ('تقدير', 'Estimate'),
  'common.days': ('{min}–{max} يوم', '{min}–{max} days'),
  'trust.green': ('موثوق', 'Trusted'),
  'trust.yellow': ('متوسط', 'Medium'),
  'trust.red': ('حذر', 'Caution'),
  'trust.unknown': ('غير مقيّم', 'Unrated'),
  'profile.title': ('حسابي', 'Profile'),
  'profile.mock_user': ('مستخدم تجريبي', 'Demo user'),
  'profile.mock_email': ('demo@factoryfinder.app', 'demo@factoryfinder.app'),
  'profile.language': ('اللغة', 'Language'),
  'profile.language_ar': ('العربية', 'العربية'),
  'profile.language_en': ('English', 'English'),
  'profile.currency': ('عملة العرض', 'Display currency'),
  'profile.destination': ('وجهة التسليم الافتراضية', 'Default destination'),
  'profile.theme': ('الوضع الليلي', 'Dark mode'),
  'profile.watchlist': ('قائمة المتابعة', 'Watchlist'),
  'profile.about': ('عن التطبيق', 'About'),
  'profile.about_text': ('منصة توريد ذكية: ابحث، تحقق من المورد، واحسب الكلفة لحد الباب.', 'A smart sourcing platform: search, verify suppliers, and compute the full landed cost.'),
  'location.country': ('الدولة', 'Country'),
  'location.city': ('المدينة', 'City'),
  'location.edit': ('تعديل الموقع', 'Edit location'),
  'country.CN': ('الصين', 'China'),
  'country.IQ': ('العراق', 'Iraq'),
  'country.TR': ('تركيا', 'Türkiye'),
  'country.AE': ('الإمارات', 'UAE'),
  'country.SA': ('السعودية', 'Saudi Arabia'),
  'country.DE': ('ألمانيا', 'Germany'),
  'country.IT': ('إيطاليا', 'Italy'),
  'country.US': ('أمريكا', 'United States'),
  'country.IN': ('الهند', 'India'),
  'country.EG': ('مصر', 'Egypt'),
  'country.JO': ('الأردن', 'Jordan'),
  'country.KW': ('الكويت', 'Kuwait'),
};
