import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/discover/compare_strings.dart';
import 'package:factory_finder/features/discover/data/compare_logic.dart';
import 'package:factory_finder/features/discover/data/discover_models.dart';
import 'package:factory_finder/features/discover/data/saved_search.dart';
import 'package:factory_finder/features/watchlist/data/watch_models.dart';
import 'package:factory_finder/features/watchlist/data/watch_repository.dart';
import 'package:flutter_test/flutter_test.dart';

Listing _l(String id, {String min = '1', String max = '2', String cur = 'USD'}) => Listing(
      id: id,
      source: 'mock',
      kind: ListingKind.product,
      title: 'T $id',
      price: MoneyRange(
        min: Money(amount: min, currency: cur),
        max: Money(amount: max, currency: cur),
      ),
      supplier: SupplierSummary(
        id: 's$id',
        name: 'S',
        location: const Location(countryCode: 'CN'),
      ),
    );

void main() {
  group('CompareNotifier', () {
    test('adds up to 3, rejects the 4th, toggles off', () {
      final n = CompareNotifier();
      expect(n.toggle(_l('a')), CompareToggle.added);
      expect(n.toggle(_l('b')), CompareToggle.added);
      expect(n.toggle(_l('c')), CompareToggle.added);
      expect(n.toggle(_l('d')), CompareToggle.full);
      expect(n.state, hasLength(3));
      expect(n.toggle(_l('b')), CompareToggle.removed);
      expect(n.state.map((l) => l.id), ['a', 'c']);
      n.remove('a');
      expect(n.state, hasLength(1));
      n.clear();
      expect(n.state, isEmpty);
    });
  });

  group('best index helpers', () {
    test('low / high, ties and missing values', () {
      expect(bestLowIndex([3, 1, 2]), 1);
      expect(bestHighIndex([3, 1, 2]), 0);
      expect(bestLowIndex([1, 1, 2]), isNull);
      expect(bestLowIndex([null, 5, null]), isNull);
      expect(bestLowIndex([null, 5, 4]), 2);
      expect(bestLowIndex(const []), isNull);
    });

    test('comparablePrices is null when currencies differ', () {
      final same = comparablePrices([_l('a'), _l('b', min: '3', max: '5')]);
      expect(same, [1.5, 4.0]);
      final mixed = comparablePrices([_l('a'), _l('b', cur: 'EUR')]);
      expect(mixed, [null, null]);
    });

    test('CompareLanded per-unit midpoint', () {
      const landed = CompareLanded(
        total: MoneyRange(
          min: Money(amount: '900', currency: 'USD'),
          max: Money(amount: '1100', currency: 'USD'),
        ),
        quantity: 100,
        transitDays: DayRange(min: 20, max: 30),
      );
      expect(landed.perUnitMid, 10.0);
    });
  });

  group('saved search', () {
    test('canSave and payload', () {
      expect(canSaveSearch(const ListingQuery()), isFalse);
      const q = ListingQuery(
        query: ' led ',
        kind: ListingKind.product,
        condition: ItemCondition.used,
        originCountry: 'CN',
        maxMoq: 100,
        verifiedOnly: true,
      );
      expect(canSaveSearch(q), isTrue);
      expect(savedSearchPayload(q), {
        'q': 'led',
        'kind': 'product',
        'condition': 'used',
        'origin_country': 'CN',
        'moq_max': 100,
        'verified_only': true,
      });
      expect(savedSearchTitle(q), 'led');
    });

    test('mock repo stores search watches idempotently', () async {
      final repo = MockWatchlistRepository();
      final before = (await repo.watchlist()).length;
      final a = await repo.addSearch({'q': 'led'}, title: 'led');
      final b = await repo.addSearch({'q': 'led'}, title: 'led');
      expect(a.id, b.id);
      expect(a.type, 'search');
      expect(a.search, {'q': 'led'});
      expect((await repo.watchlist()).length, before + 1);
    });

    test('WatchItem parses search', () {
      final w = WatchItem.fromJson({
        'id': 'w1',
        'type': 'search',
        'search': {'q': 'steel'},
      });
      expect(w.search, {'q': 'steel'});
      expect(w.isListing, isFalse);
    });
  });

  test('compare strings are bilingual', () {
    expect(compareStrings['ar']!.keys.toSet(), compareStrings['en']!.keys.toSet());
  });
}
