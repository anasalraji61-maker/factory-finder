import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/assistant/assistant_repository.dart';
import 'package:factory_finder/features/assistant/screens/assistant_screen.dart';
import 'package:factory_finder/features/freight/widgets/freight_widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'test_app.dart';

Widget _frame(Widget child, {TextDirection dir = TextDirection.rtl}) => MaterialApp(
      home: MediaQuery(
        data: const MediaQueryData(size: Size(360, 740), textScaler: TextScaler.linear(1.5)),
        child: Directionality(textDirection: dir, child: Scaffold(body: child)),
      ),
    );

void main() {
  setUpWidgetTests();

  testWidgets('FreightChip with a long label does not overflow at 360dp, 1.5x, RTL', (tester) async {
    tester.view.physicalSize = const Size(360, 740);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      _frame(
        Row(
          children: [
            Expanded(
              child: FreightChip('شحن بحري كامل حاوية 40 قدم عالية السعة ' * 3, icon: Icons.sailing),
            ),
          ],
        ),
      ),
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('ErrorState retry button meets the 48dp tap target', (tester) async {
    await tester.pumpWidget(_frame(ErrorState(message: 'x', onRetry: () {})));
    final size = tester.getSize(find.byType(OutlinedButton));
    expect(size.height, greaterThanOrEqualTo(48));
    expect(size.width, greaterThanOrEqualTo(48));
  });

  testWidgets('AppCard with a semantic label is exposed as a labelled button', (tester) async {
    final handle = tester.ensureSemantics();
    await tester.pumpWidget(
      _frame(AppCard(semanticLabel: 'Open deal', onTap: () {}, child: const Text('inner'))),
    );
    final data = tester.getSemantics(find.bySemanticsLabel('Open deal')).getSemanticsData();
    expect(data.hasFlag(SemanticsFlag.isButton), isTrue);
    expect(data.hasAction(SemanticsAction.tap), isTrue);
    handle.dispose();
  });

  testWidgets('assistant send button has a tooltip and 48dp target in RTL', (tester) async {
    tester.view.physicalSize = const Size(360, 740);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          assistantRepositoryProvider.overrideWithValue(
            AssistantRepository(ApiClient(baseUrl: 'http://localhost', isMock: true)),
          ),
        ],
        child: const MaterialApp(
          locale: Locale('ar'),
          home: Directionality(textDirection: TextDirection.rtl, child: AssistantScreen()),
        ),
      ),
    );
    await settle(tester, frames: 2);
    final send = find.byIcon(Icons.send_rounded);
    expect(send, findsOneWidget);
    final btn = find.ancestor(of: send, matching: find.byType(IconButton));
    expect(tester.widget<IconButton>(btn).tooltip, isNotEmpty);
    expect(tester.getSize(btn).shortestSide, greaterThanOrEqualTo(48));
  });
}
