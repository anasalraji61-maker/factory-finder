import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'test_app.dart';

void main() {
  setUpWidgetTests();

  // Real app, mock repos, 360dp-wide phone, system text scale 2.0.
  // Any RenderFlex overflow is reported as an exception and fails the test.
  for (final route in ['/discover', '/profile', '/settings', '/listing/lst_001']) {
    testWidgets('text scale 2.0 at 360dp: $route does not overflow', (tester) async {
      tester.platformDispatcher.textScaleFactorTestValue = 2.0;
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);

      await pumpApp(tester, location: route, logicalSize: const Size(360, 740));
      await settle(tester, frames: 6);

      expect(tester.takeException(), isNull);
      await disposeApp(tester);
    });
  }

  testWidgets('AppNetworkImage is decorative unless a label is given', (tester) async {
    final handle = tester.ensureSemantics();
    await tester.pumpWidget(
      const MaterialApp(
        home: Column(
          children: [
            AppNetworkImage(url: null, width: 40, height: 40),
            AppNetworkImage(url: null, width: 40, height: 40, semanticLabel: 'Factory photo'),
          ],
        ),
      ),
    );
    expect(find.bySemanticsLabel('Factory photo'), findsOneWidget);
    handle.dispose();
  });
}
