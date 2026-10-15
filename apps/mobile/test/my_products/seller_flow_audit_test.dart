import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/my_products/import/import_logic.dart';
import 'package:factory_finder/features/my_products/import/import_models.dart';
import 'package:factory_finder/features/my_products/my_products_logic.dart';
import 'package:factory_finder/features/my_products/my_products_models.dart';
import 'package:flutter_test/flutter_test.dart';

ProductDraft _ok({
  String priceMin = '2.50',
  String priceMax = '4.00',
  String moq = '10',
  List<String> images = const <String>[],
}) =>
    ProductDraft(
      title: 'LED panel',
      category: 'lighting',
      priceMin: priceMin,
      priceMax: priceMax,
      moq: moq,
      images: images,
    );

String _csv(List<String> rows) =>
    ['external_ref,title,category,price_min,country', ...rows].join('\n');

void main() {
  group('plainDecimalString', () {
    test('never uses exponent notation and trims zeros', () {
      expect(plainDecimalString(0.0000001), '0');
      expect(plainDecimalString(0.00001), '0.00001');
      expect(plainDecimalString(2.5), '2.5');
      expect(plainDecimalString(12.0), '12');
      expect(plainDecimalString(double.nan), '');
    });

    test('toDraft weight/volume stay valid plain decimals', () {
      const l = OwnedListing(
        id: 'a',
        status: ListingStatus.draft,
        kind: ListingKind.product,
        condition: ItemCondition.used,
        title: 'Lathe',
        price: MoneyRange(
          min: Money(amount: '1.00', currency: 'USD'),
          max: Money(amount: '2.00', currency: 'USD'),
        ),
        unitWeightKg: 0.00002,
        unitVolumeM3: 3.0,
      );
      final d = l.toDraft();
      expect(d.unitWeightKg, '0.00002');
      expect(d.unitVolumeM3, '3');
      expect(d.condition, ItemCondition.used);
      expect(isPlainDecimal(d.unitWeightKg), isTrue);
    });
  });

  group('validateProductDraft', () {
    test('valid draft has no errors and keeps prices as strings', () {
      final d = _ok();
      expect(validateProductDraft(d), isEmpty);
      final body = buildListingBody(d);
      final min = (body['price'] as Map)['min'] as Map;
      expect(min['amount'], '2.50');
      expect(body['moq'], 10);
    });

    test('price edge cases', () {
      expect(validateProductDraft(_ok(priceMin: '0')).containsKey('priceMin'), isTrue);
      expect(validateProductDraft(_ok(priceMin: '0.000')).containsKey('priceMin'), isTrue);
      expect(validateProductDraft(_ok(priceMin: '1.1234567')).containsKey('priceMin'), isTrue);
      expect(validateProductDraft(_ok(priceMin: '1e3')).containsKey('priceMin'), isTrue);
      expect(validateProductDraft(_ok(priceMin: '-1')).containsKey('priceMin'), isTrue);
      expect(validateProductDraft(_ok(priceMin: '٢٫٥')), isEmpty);
      expect(validateProductDraft(_ok(priceMin: '5', priceMax: '4.99'))['priceMax'],
          'myp.err.price_range');
      expect(validateProductDraft(_ok(priceMin: '0.1', priceMax: '0.10')), isEmpty);
    });

    test('moq must be a positive integer', () {
      for (final m in ['0', '-3', '1.5', '', 'abc']) {
        expect(validateProductDraft(_ok(moq: m))['moq'], 'myp.err.moq_invalid', reason: m);
      }
      expect(validateProductDraft(_ok(moq: '١٠')), isEmpty);
    });

    test('image count and urls', () {
      final nine = List<String>.generate(9, (i) => 'https://x.test/$i.jpg');
      expect(validateProductDraft(_ok(images: nine))['images'], 'myp.err.images_many');
      expect(validateProductDraft(_ok(images: nine.sublist(0, 8))), isEmpty);
      expect(validateProductDraft(_ok(images: ['ftp://x.test/a.jpg']))['images'],
          'myp.err.image_url');
      expect(validateProductDraft(_ok(images: ['https://x.test/a b.jpg']))['images'],
          'myp.err.image_url');
    });
  });

  group('import', () {
    test('condition accepts case and brand_new alias, rejects junk', () {
      final r = parseListingCsv(
        'external_ref,title,category,price_min,country,condition\n'
        'a1,Lathe,metalworking,10,CN,Used\n'
        'a2,Lathe,metalworking,10,CN,brand new\n'
        'a3,Lathe,metalworking,10,CN,broken\n',
      );
      expect(r.rows[0].isValid, isTrue);
      expect(r.rows[0].body!['condition'], 'used');
      expect(r.rows[1].body!['condition'], 'new');
      expect(r.rows[2].isValid, isFalse);
      expect(r.rows[2].errors.single.column, 'condition');
    });

    test('error rows carry the CSV record number and columns', () {
      final r = parseListingCsv(_csv(['a1,Good title,lighting,5,CN', 'a2,Hi,lighting,abc,CNN']));
      expect(r.rows[0].isValid, isTrue);
      final bad = r.rows[1];
      expect(bad.rowNumber, 3);
      expect(bad.errors.map((e) => e.column), containsAll(['title', 'price_min', 'country']));
    });

    test('rows the server does not answer are rejected, not dropped', () async {
      final r = parseListingCsv(_csv(['a1,Good title,lighting,5,CN', 'a2,Good title,lighting,5,CN']));
      final run = await runImportBatches(r.rows, (items, dry) async {
        return const ImportResponse(
          dryRun: false,
          created: 1,
          updated: 0,
          rejected: 0,
          results: [ImportItemResult(index: 0, action: 'created', externalRef: 'a1')],
        );
      }, dryRun: false);
      expect(run.outcomes, hasLength(2));
      expect(run.outcomes[0].action, 'created');
      expect(run.outcomes[1].action, 'rejected');
      expect(run.outcomes[1].reason, 'missing_result');
    });

    test('a failing second batch keeps first batch outcomes and reports error', () async {
      final rows = [
        for (var i = 0; i < 101; i++) 'r$i,Good title,lighting,5,CN',
      ];
      final parsed = parseListingCsv(_csv(rows));
      var call = 0;
      final run = await runImportBatches(parsed.rows, (items, dry) async {
        call++;
        if (call == 2) throw StateError('boom');
        return ImportResponse(
          dryRun: false,
          created: items.length,
          updated: 0,
          rejected: 0,
          results: [
            for (var i = 0; i < items.length; i++)
              ImportItemResult(index: i, action: 'created'),
          ],
        );
      }, dryRun: false);
      expect(run.batches, 2);
      expect(run.batchesDone, 1);
      expect(run.complete, isFalse);
      expect(run.created, 100);
      expect(run.error, isA<StateError>());
    });
  });
}
