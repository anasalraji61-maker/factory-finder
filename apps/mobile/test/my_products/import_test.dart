import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/features/my_products/import/import_logic.dart';
import 'package:factory_finder/features/my_products/import/import_models.dart';
import 'package:factory_finder/features/my_products/my_products_repository.dart';
import 'package:flutter_test/flutter_test.dart';

class _FakeAdapter implements HttpClientAdapter {
  _FakeAdapter(this.handler);

  final ResponseBody Function(RequestOptions options) handler;
  final List<RequestOptions> calls = [];

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    calls.add(options);
    return handler(options);
  }

  @override
  void close({bool force = false}) {}
}

ResponseBody _json(Object body, [int status = 200]) => ResponseBody.fromString(
      jsonEncode(body),
      status,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );

ApiClient _live(_FakeAdapter adapter) {
  final dio = Dio(BaseOptions(baseUrl: 'http://fake'));
  dio.httpClientAdapter = adapter;
  return ApiClient(baseUrl: 'http://fake', isMock: false, dio: dio);
}

const String _header = 'external_ref,title,category,price_min,country';

void main() {
  group('parseCsv', () {
    test('plain rows, no trailing newline', () {
      expect(parseCsv('a,b\n1,2'), [
        ['a', 'b'],
        ['1', '2'],
      ]);
    });

    test('quoted commas, escaped quotes and embedded newlines', () {
      final rows = parseCsv('a,b,c\n"x, y","say ""hi""","l1\nl2"\n');
      expect(rows.length, 2);
      expect(rows[1], ['x, y', 'say "hi"', 'l1\nl2']);
    });

    test('strips a UTF-8 BOM', () {
      final rows = parseCsv('\uFEFFexternal_ref,title\nA1,Lamp');
      expect(rows.first.first, 'external_ref');
    });

    test('handles CRLF and CR line ends', () {
      expect(parseCsv('a,b\r\n1,2\r\n'), [
        ['a', 'b'],
        ['1', '2'],
      ]);
      expect(parseCsv('a,b\r1,2'), [
        ['a', 'b'],
        ['1', '2'],
      ]);
    });

    test('keeps Arabic text and quoted Arabic commas', () {
      final rows = parseCsv('t,d\nمصباح,"لوح، طاقة شمسية"');
      expect(rows[1], ['مصباح', 'لوح، طاقة شمسية']);
    });

    test('empty fields, tab delimiter and a mid-field quote', () {
      expect(parseCsv('a,,c\n,,')[0], ['a', '', 'c']);
      expect(parseCsv('a,,c\n,,')[1], ['', '', '']);
      expect(parseCsv('a\tb\n1\t2')[1], ['1', '2']);
      expect(parseCsv('a,b\n5" pipe,x')[1], ['5" pipe', 'x']);
    });

    test('unterminated quote throws', () {
      expect(() => parseCsv('a,b\n"oops,1'), throwsFormatException);
    });
  });

  group('parseListingCsv', () {
    test('valid row becomes an import item with external_ref and defaults', () {
      final p = parseListingCsv('$_header\nSKU-1,LED Panel,lighting,2.50,cn\n');
      expect(p.errorKey, isNull);
      expect(p.rows.length, 1);
      final r = p.rows.single;
      expect(r.isValid, isTrue);
      expect(r.rowNumber, 2);
      final b = r.body!;
      expect(b['external_ref'], 'SKU-1');
      expect(b['kind'], 'product');
      expect(b['condition'], 'new');
      expect(b['unit'], 'piece');
      expect(b['moq'], 1);
      expect((b['price'] as Map)['min'], {'amount': '2.50', 'currency': 'USD'});
      expect((b['price'] as Map)['max'], {'amount': '2.50', 'currency': 'USD'});
      expect(b['origin'], {'country_code': 'CN'});
    });

    test('full row with BOM, CRLF, Arabic digits and optional columns', () {
      final csv = '\uFEFFExternal Ref,Title,title_ar,Category,price_min,price_max,currency,'
          'moq,unit,country,kind,condition,incoterm,hs_code,lead_time_min,lead_time_max,images,city\r\n'
          'A-9,"Solar panel, 400W",لوح شمسي,solar_energy,٣٫٥,٤,eur,١٠,set,tr,'
          'raw_material,used,fob,8541.43,5,9,http://a.io/1.jpg|http://a.io/2.jpg,Izmir\r\n';
      final p = parseListingCsv(csv);
      expect(p.errorKey, isNull);
      final b = p.rows.single.body!;
      expect(p.rows.single.errors, isEmpty);
      expect(b['title'], 'Solar panel, 400W');
      expect(b['title_ar'], 'لوح شمسي');
      expect(b['kind'], 'raw_material');
      expect(b['condition'], 'used');
      expect(b['incoterm'], 'FOB');
      expect(b['hs_code'], '854143');
      expect(b['moq'], 10);
      expect((b['price'] as Map)['min'], {'amount': '3.5', 'currency': 'EUR'});
      expect(b['lead_time_days'], {'min': 5, 'max': 9});
      expect(b['images'], ['http://a.io/1.jpg', 'http://a.io/2.jpg']);
      expect(b['origin'], {'country_code': 'TR', 'city': 'Izmir'});
    });

    test('per-row errors name the column and do not block other rows', () {
      final p = parseListingCsv(
        '$_header\n'
        'ok-1,Good Lamp,lighting,1.5,CN\n'
        ',No Ref,lighting,1,CN\n'
        'ok-1,Dup Ref,lighting,1,CN\n'
        'bad-2,ab,lighting,0,CHN\n',
      );
      expect(p.validRows.length, 1);
      expect(p.invalidRows.length, 3);
      expect(p.rows[1].errors.single.column, 'external_ref');
      expect(p.rows[1].errors.single.key, 'myp.imp.err.ref_invalid');
      expect(p.rows[2].errors.single.key, 'myp.imp.err.ref_duplicate');
      final cols = p.rows[3].errors.map((e) => e.column).toSet();
      expect(cols, containsAll(<String>['title', 'price_min', 'country']));
      expect(p.rows[3].rowNumber, 5);
    });

    test('rejects bad kind, condition, incoterm and currency', () {
      final p = parseListingCsv(
        'external_ref,title,category,price_min,country,kind,condition,incoterm,currency\n'
        'r1,Some Title,lighting,1,CN,gadget,broken,XXX,DOLLAR\n',
      );
      final keys = p.rows.single.errors.map((e) => e.key).toSet();
      expect(keys, {
        'myp.imp.err.kind',
        'myp.imp.err.condition',
        'myp.imp.err.incoterm',
        'myp.imp.err.currency',
      });
    });

    test('whole-input errors', () {
      expect(parseListingCsv('   \n ').errorKey, 'myp.imp.err.empty');
      expect(parseListingCsv(_header).errorKey, 'myp.imp.err.no_rows');
      expect(parseListingCsv('a,"b\n1,2').errorKey, 'myp.imp.err.quote');
      final miss = parseListingCsv('external_ref,title\nx,Lamp');
      expect(miss.errorKey, 'myp.imp.err.columns');
      expect(miss.missingColumns, ['category', 'price_min', 'country']);
    });

    test('country_code header is an alias for country', () {
      final p = parseListingCsv(
        'external_ref,title,category,price_min,country_code\nr1,Lamp One,lighting,1,CN',
      );
      expect(p.rows.single.isValid, isTrue);
    });
  });

  group('chunking', () {
    String bigCsv(int n) {
      final b = StringBuffer('$_header\n');
      for (var i = 0; i < n; i++) {
        b.writeln('r$i,Lamp $i,lighting,1,CN');
      }
      return b.toString();
    }

    test('chunkItems splits at the limit', () {
      final chunks = chunkItems<int>(List<int>.generate(250, (i) => i));
      expect(chunks.map((c) => c.length).toList(), [100, 100, 50]);
      expect(chunkItems<int>(<int>[]), isEmpty);
    });

    test('runImportBatches sends 100 per call and maps indexes back to rows', () async {
      final parsed = parseListingCsv(bigCsv(230));
      expect(parsed.batchCount, 3);
      final sizes = <int>[];
      final run = await runImportBatches(
        parsed.rows,
        (items, dry) async {
          sizes.add(items.length);
          return ImportResponse(
            dryRun: dry,
            created: items.length,
            updated: 0,
            rejected: 0,
            results: [
              for (var i = 0; i < items.length; i++)
                ImportItemResult(index: i, action: 'created'),
            ],
          );
        },
        dryRun: false,
      );
      expect(sizes, [100, 100, 30]);
      expect(run.created, 230);
      expect(run.complete, isTrue);
      expect(run.outcomes.first.rowNumber, 2);
      expect(run.outcomes.last.externalRef, 'r229');
    });

    test('a failing batch keeps earlier outcomes and reports the error', () async {
      final parsed = parseListingCsv(bigCsv(150));
      var call = 0;
      final run = await runImportBatches(
        parsed.rows,
        (items, dry) async {
          call++;
          if (call == 2) {
            throw ApiException(status: 429, code: 'rate_limited', message: 'slow down');
          }
          return ImportResponse(
            dryRun: dry,
            created: items.length,
            updated: 0,
            rejected: 0,
            results: [
              for (var i = 0; i < items.length; i++)
                ImportItemResult(index: i, action: 'created'),
            ],
          );
        },
        dryRun: true,
      );
      expect(run.error, isA<ApiException>());
      expect(run.batchesDone, 1);
      expect(run.created, 100);
      expect(run.complete, isFalse);
    });

    test('invalid rows are never sent and appear as invalid outcomes', () async {
      final parsed = parseListingCsv(
        '$_header\nok,Good Lamp,lighting,1,CN\nbad,x,lighting,1,CN\n',
      );
      var sent = 0;
      final run = await runImportBatches(
        parsed.rows,
        (items, dry) async {
          sent += items.length;
          return ImportResponse(
            dryRun: dry,
            created: 0,
            updated: 0,
            rejected: 1,
            results: [
              ImportItemResult(index: 0, action: 'rejected', reason: 'conflict'),
            ],
          );
        },
        dryRun: true,
      );
      expect(sent, 1);
      expect(run.rejected, 1);
      expect(run.invalid, 1);
      expect(run.outcomes.map((o) => o.action).toList(), ['rejected', 'invalid']);
      expect(run.outcomes.first.reason, 'conflict');
    });
  });

  group('repository', () {
    test('ImportResponse.fromJson is tolerant', () {
      final r = ImportResponse.fromJson({
        'dry_run': true,
        'created': 1,
        'updated': 0,
        'rejected': 1,
        'results': [
          {'index': 0, 'external_ref': 'a', 'action': 'created'},
          {'index': 1, 'action': 'rejected', 'reason': 'validation_error', 'message': 'title'},
          'junk',
        ],
      });
      expect(r.dryRun, isTrue);
      expect(r.results.length, 2);
      expect(r.results[1].reason, 'validation_error');
      expect(r.results[1].isRejected, isTrue);
      expect(ImportResponse.fromJson(null).results, isEmpty);
    });

    test('live call posts items and dry_run to /v1/my/listings/import', () async {
      final adapter = _FakeAdapter((o) => _json({
            'dry_run': true,
            'created': 1,
            'updated': 0,
            'rejected': 0,
            'results': [
              {'index': 0, 'external_ref': 'SKU-1', 'action': 'created'},
            ],
          }));
      final repo = MyListingsRepository(_live(adapter));
      final parsed = parseListingCsv('$_header\nSKU-1,LED Panel,lighting,2.50,CN');
      final resp = await repo.importListings(
        <Map<String, dynamic>>[parsed.rows.single.body!],
        dryRun: true,
      );
      final call = adapter.calls.single;
      expect(call.method, 'POST');
      expect(call.path, '/v1/my/listings/import');
      final body = call.data as Map;
      expect(body['dry_run'], true);
      expect((body['items'] as List).single['external_ref'], 'SKU-1');
      expect(resp.created, 1);
    });

    test('mock backend creates, is idempotent on external_ref, and dry run saves nothing', () async {
      final backend = MockMyListingsBackend();
      final repo = MyListingsRepository(
        ApiClient(baseUrl: 'http://unused.invalid', isMock: true),
        backend,
      );
      final parsed = parseListingCsv(
        '$_header\nA,Lamp One,lighting,1,CN\nB,Lamp Two,lighting,2,CN\nA,Lamp One,lighting,1,CN\n',
      );
      // Row 3 repeats A: the file-level check already marks it invalid.
      expect(parsed.rows[2].isValid, isFalse);
      final items = <Map<String, dynamic>>[
        for (final r in parsed.validRows) r.body!,
      ];

      final dry = await repo.importListings(items, dryRun: true);
      expect(dry.created, 2);
      expect(backend.items, isEmpty);

      final first = await repo.importListings(items);
      expect(first.created, 2);
      expect(backend.items.length, 2);

      final again = await repo.importListings(items);
      expect(again.updated, 2);
      expect(again.created, 0);
      expect(backend.items.length, 2);

      final dup = await repo.importListings(<Map<String, dynamic>>[items.first, items.first]);
      expect(dup.rejected, 1);
      expect(dup.results[1].reason, 'duplicate_in_batch');

      await expectLater(
        repo.importListings(<Map<String, dynamic>>[]),
        throwsA(isA<ApiException>()),
      );
    });
  });
}
