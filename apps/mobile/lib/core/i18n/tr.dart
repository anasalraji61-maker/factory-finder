import 'package:factory_finder/core/i18n/core_strings.dart';
import 'package:flutter/widgets.dart';

/// Builds `{'ar': {...}, 'en': {...}}` from `key: (arabic, english)` pairs,
/// guaranteeing every key exists in both languages.
Map<String, Map<String, String>> bilingual(Map<String, (String, String)> pairs) {
  final ar = <String, String>{};
  final en = <String, String>{};
  pairs.forEach((key, value) {
    ar[key] = value.$1;
    en[key] = value.$2;
  });
  return {'ar': ar, 'en': en};
}

class AppStrings {
  AppStrings._();

  static final Map<String, Map<String, String>> _tables = {};
  static bool _coreLoaded = false;

  static void _ensureCore() {
    if (_coreLoaded) return;
    _coreLoaded = true;
    register(coreStrings);
  }

  /// Merge [tables] into the registry.
  static void register(Map<String, Map<String, String>> tables) {
    tables.forEach((lang, entries) {
      final target = _tables.putIfAbsent(lang, () => <String, String>{});
      target.addAll(entries);
    });
  }

  static String lookup(
    String languageCode,
    String key, [
    Map<String, String> args = const {},
  ]) {
    _ensureCore();
    var text = _tables[languageCode]?[key] ?? _tables['en']?[key] ?? key;
    args.forEach((name, value) {
      text = text.replaceAll('{$name}', value);
    });
    return text;
  }
}

extension TrX on BuildContext {
  /// String for the current locale (fallback: en, then the key).
  String tr(String key, [Map<String, String> args = const {}]) {
    final code = Localizations.localeOf(this).languageCode;
    return AppStrings.lookup(code, key, args);
  }
}

/// Merges several `{'ar': {...}, 'en': {...}}` tables into one.
Map<String, Map<String, String>> mergeStringTables(
  List<Map<String, Map<String, String>>> tables,
) {
  final out = <String, Map<String, String>>{};
  for (final t in tables) {
    t.forEach((lang, entries) {
      out.putIfAbsent(lang, () => <String, String>{}).addAll(entries);
    });
  }
  return out;
}
