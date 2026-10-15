import 'package:factory_finder/core/providers.dart';
import 'package:flutter/widgets.dart';

const String _arabicIndic = '٠١٢٣٤٥٦٧٨٩';

/// Converts ASCII digits in [text] to Arabic-Indic digits when [style] asks
/// for it. Other characters (including separators) are left untouched.
String localizeDigits(String text, DigitStyle style) {
  if (style == DigitStyle.western) return text;
  final b = StringBuffer();
  var verbatimDepth = 0;
  for (final unit in text.codeUnits) {
    if (unit == _fsi) {
      verbatimDepth++;
    } else if (unit == _pdi && verbatimDepth > 0) {
      verbatimDepth--;
    }
    if (verbatimDepth == 0 && unit >= 0x30 && unit <= 0x39) {
      b.write(_arabicIndic[unit - 0x30]);
    } else {
      b.writeCharCode(unit);
    }
  }
  return b.toString();
}

const int _fsi = 0x2068;
const int _pdi = 0x2069;

/// Marks [id] (container number, HS code, reference, supplier id...) so
/// [localizeDigits] never converts its digits. Wrap ids before passing them
/// as `context.tr` args; the FSI/PDI isolate also keeps them from reordering.
String verbatim(String id) => id.isEmpty ? id : '\u2068$id\u2069';

/// Like [localizeDigits] but for a formatted amount: also swaps the decimal
/// and thousands separators for their Arabic forms.
String localizeNumber(String text, DigitStyle style) {
  if (style == DigitStyle.western) return text;
  final swapped = text.replaceAll(',', '٬').replaceAll('.', '٫');
  return localizeDigits(swapped, style);
}

/// Provides the user's [DigitStyle] to the widget tree. `context.tr` and
/// `MoneyText` read it, so changing the setting re-renders text app-wide.
class DigitStyleScope extends InheritedWidget {
  const DigitStyleScope({super.key, required this.style, required super.child});

  final DigitStyle style;

  static DigitStyle of(BuildContext context) {
    DigitStyleScope? scope;
    try {
      scope = context.dependOnInheritedWidgetOfExactType<DigitStyleScope>();
    } catch (_) {
      // Called outside build (e.g. initState / callbacks): read without
      // subscribing.
      scope = context.getInheritedWidgetOfExactType<DigitStyleScope>();
    }
    return scope?.style ?? DigitStyle.western;
  }

  @override
  bool updateShouldNotify(DigitStyleScope oldWidget) => style != oldWidget.style;
}
