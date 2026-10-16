import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/logistics/data/logistics_repository.dart';
import 'package:factory_finder/features/logistics/data/quote_request.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../widgets/test_app.dart';

const Listing _listing = Listing(
  id: 'lst_not_in_fixture',
  source: 'mock',
  kind: ListingKind.product,
  title: 'Steel Bolts',
  price: MoneyRange(
    min: Money(amount: '2', currency: 'USD'),
    max: Money(amount: '4', currency: 'USD'),
  ),
  supplier: SupplierSummary(
    id: 'sup_1',
    name: 'Bolt Co',
    location: Location(countryCode: 'VN', city: 'Hanoi'),
  ),
  moq: 250,
  unitWeightKg: 0.2,
);

void main() {
  setUpWidgetTests();

  test('ListingPrefill.fromListing uses MOQ, mid price and supplier origin', () {
    final p = ListingPrefill.fromListing(_listing);
    expect(p.listingId, 'lst_not_in_fixture');
    expect(p.quantity, 250);
    expect(p.unitPrice, 3);
    expect(p.currency, 'USD');
    expect(p.origin.countryCode, 'VN');
    expect(p.incoterm, Incoterm.fob);
  });

  testWidgets('calculator fills from the handed-over listing (any id)', (tester) async {
    await pumpApp(
      tester,
      location: '/logistics/calculator?listing_id=lst_not_in_fixture',
      overrides: [
        listingPrefillSeedProvider
            .overrideWith((ref) => ListingPrefill.fromListing(_listing)),
      ],
    );
    final fields = find.byType(TextField);
    String text(int i) => tester.widget<TextField>(fields.at(i)).controller!.text;
    expect(text(0), '3');
    expect(text(1), '250');
    expect(text(2), '50');
    expect(find.byKey(const ValueKey<String>('calc_prefill_failed')), findsNothing);
    await disposeApp(tester);
  });
}
