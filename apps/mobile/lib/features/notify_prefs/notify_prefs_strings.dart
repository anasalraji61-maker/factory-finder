import 'package:factory_finder/core/i18n/tr.dart';

final Map<String, Map<String, String>> notifyPrefsStrings = bilingual(_pairs);

const Map<String, (String, String)> _pairs = {
  'notifyprefs.tile': ('إعدادات الإشعارات', 'Notification settings'),
  'notifyprefs.title': ('إعدادات الإشعارات', 'Notification settings'),
  'notifyprefs.channels': ('قنوات التنبيه', 'Alert channels'),
  'notifyprefs.in_app_note': ('التنبيهات داخل التطبيق تظهر دائماً في صندوق الوارد.', 'In-app alerts always appear in your inbox.'),
  'notifyprefs.channel.in_app': ('داخل التطبيق', 'In-app'),
  'notifyprefs.channel.push': ('إشعار فوري', 'Push'),
  'notifyprefs.channel.email': ('بريد إلكتروني', 'Email'),
  'notifyprefs.type.price_drop': ('انخفاض السعر', 'Price drop'),
  'notifyprefs.type.below_target': ('تحت السعر المستهدف', 'Below target price'),
  'notifyprefs.type.cheaper_equivalent': ('بديل أرخص', 'Cheaper equivalent'),
  'notifyprefs.type.back_in_stock': ('عودة التوفر', 'Back in stock'),
  'notifyprefs.type.new_results': ('نتائج جديدة', 'New results'),
  'notifyprefs.quiet_title': ('ساعات الهدوء', 'Quiet hours'),
  'notifyprefs.quiet_hint': ('تُؤجَّل الإشعارات الفورية خلال هذه الفترة ولا تُلغى.', 'Push notifications are deferred, not dropped, during this window.'),
  'notifyprefs.quiet_enable': ('تفعيل ساعات الهدوء', 'Enable quiet hours'),
  'notifyprefs.quiet_start': ('من', 'From'),
  'notifyprefs.quiet_end': ('إلى', 'To'),
  'notifyprefs.timezone': ('المنطقة الزمنية', 'Timezone'),
  'notifyprefs.language': ('لغة الإشعارات', 'Notification language'),
  'notifyprefs.email': ('بريد الملخص اليومي', 'Daily digest email'),
  'notifyprefs.email_hint': ('اتركه فارغاً لإيقاف الملخص', 'Leave empty for no digest'),
  'notifyprefs.err_email': ('أدخل بريداً إلكترونياً صحيحاً', 'Enter a valid email address'),
  'notifyprefs.save': ('حفظ التغييرات', 'Save changes'),
  'notifyprefs.saved': ('تم حفظ الإعدادات', 'Settings saved'),
  'notifyprefs.save_failed': ('تعذر حفظ الإعدادات', 'Could not save settings'),
  'notifyprefs.login_required': ('سجّل الدخول لإدارة الإشعارات', 'Sign in to manage notifications'),
};
