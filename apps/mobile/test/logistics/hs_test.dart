import 'package:factory_finder/features/logistics/data/hs_repository.dart';
import 'package:factory_finder/features/logistics/data/logistics_repository.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('HsSearchResult.fromJson parses the contract shape', () {
    final r = HsSearchResult.fromJson({
      'items': [
        {
          'code': '851830',
          'chapter': '85',
          'description_en': 'Headphones',
          'description_ar': 'سماعات',
          'typical_duty_percent_hint': 5,
          'keywords': ['earbuds'],
        },
        {'code': '999999', 'typical_duty_percent_hint': '7.5'},
        {'code': '000000', 'typical_duty_percent_hint': null},
      ],
      'total': 3,
      'destination_country': 'IQ',
      'disclaimer': 'Estimate only',
    });
    expect(r.items.length, 3);
    expect(r.total, 3);
    expect(r.destinationCountry, 'IQ');
    expect(r.disclaimer, 'Estimate only');
    expect(r.items[0].dutyHintPercent, 5.0);
    expect(r.items[0].description('ar'), 'سماعات');
    expect(r.items[0].description('en'), 'Headphones');
    expect(r.items[1].dutyHintPercent, 7.5);
    expect(r.items[2].dutyHintPercent, isNull);
  });

  test('HsSearchResult.fromJson tolerates an empty body', () {
    final r = HsSearchResult.fromJson(<String, dynamic>{});
    expect(r.items, isEmpty);
    expect(r.total, 0);
  });

  test('mock search matches code prefix, description and keywords', () {
    expect(kMockHsItems.length, greaterThanOrEqualTo(15));
    expect(searchMockHs('8518').items.single.code, '851830');
    expect(searchMockHs('earbuds').items.first.code, '851830');
    expect(searchMockHs('steel').items.length, 2);
    expect(searchMockHs('zzzz').items, isEmpty);
    expect(searchMockHs('steel', limit: 1).items.length, 1);
    expect(searchMockHs('steel', limit: 1).total, 2);
    expect(searchMockHs('led', destinationCountry: 'IQ').destinationCountry, 'IQ');
  });

  test('mock HS suggestions are deterministic, capped and bilingual', () {
    expect(suggestMockHs('steel').map((e) => e.hs6), ['721420', '720836']);
    expect(suggestMockHs('steel', limit: 1).length, 1);
    expect(suggestMockHs('  ').isEmpty, isTrue);
    expect(suggestMockHs('zzzz').isEmpty, isTrue);
    expect(suggestMockHs('earbuds').single.description('ar'), 'سماعات رأس وأذن');
    final s = HsSuggestion.fromJson({'hs6': '851830', 'description_en': 'X', 'confidence': 'medium'});
    expect(s.hs6, '851830');
    expect(s.description('ar'), 'X');
  });
}
