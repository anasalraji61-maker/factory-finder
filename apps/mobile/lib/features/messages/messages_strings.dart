import 'package:factory_finder/core/i18n/tr.dart';

final Map<String, Map<String, String>> messagesStrings = bilingual(_pairs);

const Map<String, (String, String)> _pairs = {
  'messages.title': ('الرسائل', 'Messages'),
  'messages.empty_title': ('لا توجد محادثات بعد', 'No conversations yet'),
  'messages.empty_msg': ('ابدأ محادثة مع مورّد من صفحة المنتج أو المورّد.', 'Start a chat with a supplier from a listing or supplier page.'),
  'messages.yesterday': ('أمس', 'Yesterday'),
  'messages.today': ('اليوم', 'Today'),
  'messages.ctx.listing': ('منتج', 'Listing'),
  'messages.ctx.request': ('طلب', 'Request'),
  'messages.ctx.deal': ('صفقة', 'Deal'),
  'messages.composer_hint': ('اكتب رسالة...', 'Type a message...'),
  'messages.send': ('إرسال', 'Send'),
  'messages.attach': ('إرفاق ملف', 'Attach file'),
  'messages.attach_soon': ('إرفاق الملفات سيتوفر قريباً', 'Attachments are coming soon'),
  'messages.failed': ('فشل الإرسال — اضغط لإعادة المحاولة', 'Not sent — tap to retry'),
  'messages.sending': ('جارٍ الإرسال', 'Sending'),
  'messages.chat_empty': ('ابدأ المحادثة بأول رسالة', 'Say hello to start the chat'),
  'messages.conn.connecting': ('جارٍ الاتصال...', 'Connecting...'),
  'messages.conn.live': ('مباشر', 'Live'),
  'messages.conn.reconnecting': ('إعادة الاتصال...', 'Reconnecting...'),
  'messages.conn.failed': ('غير متصل بالتحديث المباشر', 'Live updates unavailable'),
  'messages.new.title': ('محادثة جديدة', 'New conversation'),
  'messages.new.supplier': ('المورّد', 'Supplier'),
  'messages.new.listing': ('بخصوص المنتج', 'About listing'),
  'messages.new.first': ('رسالتك الأولى (اختياري)', 'Your first message (optional)'),
  'messages.new.start': ('ابدأ المحادثة', 'Start chat'),
  'messages.new.no_supplier': ('لم يتم تحديد مورّد', 'No supplier selected'),
  'messages.new.default_text': ('مرحباً، أرغب بالاستفسار عن هذا المنتج.', 'Hello, I would like to ask about this product.'),
};
