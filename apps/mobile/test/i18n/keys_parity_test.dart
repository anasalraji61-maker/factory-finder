import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

// Source-level i18n audit (no network, no app boot). Every string table is
// declared as `'key': ('arabic', 'english')`, so ar/en key parity is
// structural; this test additionally checks each pair is non-empty, that
// `{placeholders}` match between languages, and that keys are not duplicated.
final _pair = RegExp(
  r"'([A-Za-z0-9_.\-]+)'\s*:\s*\(\s*'((?:[^'\\]|\\.)*)'\s*,\s*'((?:[^'\\]|\\.)*)'\s*,?\s*\)",
  dotAll: true,
);
final _ph = RegExp(r'\{([A-Za-z0-9_]+)\}');

List<File> _stringFiles() => Directory('lib')
    .listSync(recursive: true)
    .whereType<File>()
    .where((f) => f.path.endsWith('_strings.dart'))
    .toList();

void main() {
  test('every string table pair is non-empty with matching placeholders', () {
    final files = _stringFiles();
    expect(files, isNotEmpty);
    final problems = <String>[];
    var total = 0;
    for (final f in files) {
      final seen = <String>{};
      for (final m in _pair.allMatches(f.readAsStringSync())) {
        total++;
        final key = m.group(1)!, ar = m.group(2)!, en = m.group(3)!;
        if (!seen.add(key)) problems.add('${f.path}: duplicate key $key');
        if (ar.trim().isEmpty || en.trim().isEmpty) {
          problems.add('${f.path}: empty ar/en for $key');
        }
        final pa = _ph.allMatches(ar).map((e) => e.group(1)).toSet();
        final pe = _ph.allMatches(en).map((e) => e.group(1)).toSet();
        if (pa.length != pe.length || !pa.containsAll(pe)) {
          problems.add('${f.path}: placeholder mismatch for $key');
        }
      }
    }
    expect(total, greaterThan(100));
    expect(problems, isEmpty, reason: problems.join('\n'));
  });

  test('every context.tr literal key exists in some string table', () {
    final known = <String>{};
    for (final f in _stringFiles()) {
      for (final m in _pair.allMatches(f.readAsStringSync())) {
        known.add(m.group(1)!);
      }
    }
    final use = RegExp(r"""\.tr\(\s*'([a-z0-9_]+(?:\.[a-z0-9_]+)+)'""");
    final missing = <String>{};
    for (final f in Directory('lib').listSync(recursive: true).whereType<File>()) {
      if (!f.path.endsWith('.dart') || f.path.endsWith('_strings.dart')) continue;
      for (final m in use.allMatches(f.readAsStringSync())) {
        if (!known.contains(m.group(1))) missing.add('${f.path}: ${m.group(1)}');
      }
    }
    expect(missing, isEmpty, reason: missing.join('\n'));
  });
}
