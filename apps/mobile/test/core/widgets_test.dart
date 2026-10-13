import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('TrustBadge and PrimaryButton render and respond', (tester) async {
    var taps = 0;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Column(
            children: [
              const TrustBadge(band: TrustBand.green, score: 86),
              const TrustBadge(band: TrustBand.red, compact: true, score: 30),
              PrimaryButton(label: 'Go', onPressed: () => taps++),
              const MoneyText(Money(amount: '12.5', currency: 'USD')),
            ],
          ),
        ),
      ),
    );

    expect(find.text('Trusted 86'), findsOneWidget);
    expect(find.text('30'), findsOneWidget);
    expect(find.text(r'$12.50'), findsOneWidget);
    await tester.tap(find.text('Go'));
    await tester.pump();
    expect(taps, 1);
  });

  test('CountryFlag emoji', () {
    expect(CountryFlag.emoji('CN'), '🇨🇳');
    expect(CountryFlag.emoji('iq'), '🇮🇶');
  });
}
