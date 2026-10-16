/// Pure form validators. Each returns an i18n key for the error, or null.

String? validateRfqTitle(String? v) {
  final t = (v ?? '').trim();
  if (t.isEmpty) return 'req.err.title_required';
  if (t.length < 3) return 'req.err.title_short';
  return null;
}

String? validateRfqQuantity(String? v) {
  final t = (v ?? '').trim();
  if (t.isEmpty) return 'req.err.qty_required';
  final n = double.tryParse(t);
  if (n == null || n <= 0) return 'req.err.qty_invalid';
  return null;
}

/// Optional: empty is valid; otherwise must be a positive number.
String? validateRfqTargetPrice(String? v) {
  final t = (v ?? '').trim();
  if (t.isEmpty) return null;
  final n = double.tryParse(t);
  if (n == null || n <= 0) return 'req.err.price_invalid';
  return null;
}

/// Required offer unit price: a positive decimal.
String? validateOfferPrice(String? v) {
  final t = (v ?? '').trim();
  if (t.isEmpty) return 'req.err.price_required';
  final n = double.tryParse(t);
  if (n == null || n <= 0) return 'req.err.price_invalid';
  return null;
}

String? validateOfferSupplierName(String? v) {
  if ((v ?? '').trim().isEmpty) return 'req.err.supplier_name_required';
  return null;
}

/// Optional whole number in [0, [max]]: empty is valid.
String? validateOfferInt(String? v, {int max = 1000000000}) {
  final t = (v ?? '').trim();
  if (t.isEmpty) return null;
  final n = int.tryParse(t);
  if (n == null || n < 0 || n > max) return 'req.err.int_invalid';
  return null;
}

/// Optional: null is valid; otherwise must not be before [today].
String? validateRfqDeadline(DateTime? deadline, DateTime today) {
  if (deadline == null) return null;
  final d = DateTime(deadline.year, deadline.month, deadline.day);
  final t = DateTime(today.year, today.month, today.day);
  if (d.isBefore(t)) return 'req.err.deadline_past';
  return null;
}

/// Normalises a number typed by the user (Arabic-Indic digits, comma decimal).
String normalizeNumberInput(String s) {
  const ar = '٠١٢٣٤٥٦٧٨٩';
  final buf = StringBuffer();
  for (final r in s.trim().runes) {
    final c = String.fromCharCode(r);
    final i = ar.indexOf(c);
    if (i >= 0) {
      buf.write(i);
    } else if (c == '٫' || c == ',') {
      buf.write('.');
    } else {
      buf.write(c);
    }
  }
  return buf.toString();
}
