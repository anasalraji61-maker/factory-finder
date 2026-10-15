import 'package:factory_finder/core/i18n/tr.dart';

final Map<String, Map<String, String>> checklistStrings = bilingual({
  'checklist.title': ('قائمة وثائق الاستيراد', 'Import checklist'),
  'checklist.destination': ('بلد الوجهة: {country}', 'Destination: {country}'),
  'checklist.incoterm': ('شروط التسليم (إنكوتيرمز)', 'Incoterm'),
  'checklist.progress': ('{done} من {total} مكتملة', '{done} of {total} done'),
  'checklist.guidance_badge': ('إرشادية فقط', 'Guidance only'),
  'checklist.disclaimer': (
    'هذه القائمة إرشادية وعامة. تختلف المتطلبات حسب نوع البضاعة والبلد والجهة المستوردة وقد تتغير، لذا تأكد منها دائماً مع المخلّص الجمركي قبل الشحن.',
    'This checklist is general guidance only. Requirements vary by product, country and importer and may change, so always confirm them with a customs broker before shipping.',
  ),
  'checklist.doc.invoice': ('الفاتورة التجارية', 'Commercial invoice'),
  'checklist.doc.invoice.hint': ('من المورد، تتضمن الوصف والكمية والسعر.', 'From the supplier: description, quantity and price.'),
  'checklist.doc.packing': ('قائمة التعبئة', 'Packing list'),
  'checklist.doc.packing.hint': ('عدد الطرود والأوزان والأبعاد.', 'Package count, weights and dimensions.'),
  'checklist.doc.transport': ('بوليصة الشحن (بحري BL / جوي AWB)', 'Bill of lading (BL) / air waybill (AWB)'),
  'checklist.doc.transport.hint': ('من شركة النقل، مطلوبة لتسلّم البضاعة.', 'Issued by the carrier; needed to collect the goods.'),
  'checklist.doc.origin': ('شهادة المنشأ', 'Certificate of origin'),
  'checklist.doc.origin.hint': ('تثبت بلد التصنيع وقد تؤثر على الرسوم.', 'Proves where goods were made; may affect duties.'),
  'checklist.doc.conformity': ('شهادة المطابقة (إن لزمت)', 'Conformity certificate (where applicable)'),
  'checklist.doc.conformity.hint': ('لبعض السلع المنظّمة حسب جهة التقييس في بلد الوجهة.', 'For regulated goods, per the destination standards body.'),
  'checklist.doc.insurance': ('وثيقة التأمين', 'Insurance certificate'),
  'checklist.doc.insurance.hint': ('تأمين البضاعة أثناء النقل.', 'Cover for the goods in transit.'),
  'checklist.doc.insurance.included': ('تأمين البضاعة أثناء النقل؛ يتحمّله البائع عادةً بهذا الشرط، تحقق من تغطيته.', 'Cargo cover in transit; usually arranged by the seller under this term, so verify the cover.'),
  'checklist.doc.licence': ('إجازة الاستيراد (إن لزمت)', 'Import licence (if required)'),
  'checklist.doc.licence.hint': ('لسلع مقيّدة أو خاضعة لموافقة مسبقة.', 'For restricted goods or those needing prior approval.'),
});
