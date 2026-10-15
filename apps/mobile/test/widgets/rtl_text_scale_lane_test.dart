import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'test_app.dart';

void main() {
  setUpWidgetTests();

  // Arabic (RTL) is the default locale; 360dp wide, system text scale 1.5.
  for (final route in ['/discover', '/messages', '/compare', '/verification', '/listing/lst_001']) {
    testWidgets('RTL + text scale 1.5 at 360dp: $route does not overflow', (tester) async {
      tester.platformDispatcher.textScaleFactorTestValue = 1.5;
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);

      await pumpApp(tester, location: route, logicalSize: const Size(360, 740));
      await settle(tester, frames: 6);

      expect(tester.takeException(), isNull);
      await disposeApp(tester);
    });
  }

  test('discover/messages/trust sources use directional insets and alignments', () {
    final bad = RegExp(
      r'EdgeInsets\.only\([^)]*\b(left|right)\s*:|Alignment\.(top|center|bottom)(Left|Right)\b',
    );
    for (final dir in ['discover', 'messages', 'trust']) {
      for (final f in Directory('lib/features/$dir').listSync(recursive: true)) {
        if (f is File && f.path.endsWith('.dart')) {
          expect(bad.hasMatch(f.readAsStringSync()), isFalse, reason: f.path);
        }
      }
    }
  });
}
