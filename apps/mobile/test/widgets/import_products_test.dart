import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/features/my_products/import/import_models.dart';
import 'package:factory_finder/features/my_products/my_products_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'test_app.dart';

class _FixedAuth extends AuthController {
  _FixedAuth(Ref ref, Me me) : super(ref) {
    state = me;
  }
}

const Me _verified = Me(
  id: 'usr_s',
  name: 'Supplier',
  supplierId: 'sup_iq_001',
  supplierClaimStatus: 'verified',
);

/// Records every import call; rejects refs listed in [rejectRefs] and throws
/// a rate-limit error on call number [failOnCall].
class _FakeRepo extends MyListingsRepository {
  _FakeRepo({this.rejectRefs = const <String>{}, this.failOnCall})
      : super(ApiClient(baseUrl: 'http://unused.invalid', isMock: true));

  final Set<String> rejectRefs;
  final int? failOnCall;
  final List<bool> dryFlags = <bool>[];
  final List<int> sizes = <int>[];

  @override
  Future<ImportResponse> importListings(
    List<Map<String, dynamic>> items, {
    bool dryRun = false,
  }) async {
    dryFlags.add(dryRun);
    sizes.add(items.length);
    if (failOnCall != null && sizes.length == failOnCall) {
      throw ApiException(status: 429, code: 'rate_limited', message: 'slow');
    }
    final results = <ImportItemResult>[];
    var created = 0;
    var rejected = 0;
    for (var i = 0; i < items.length; i++) {
      final ref = items[i]['external_ref'] as String;
      if (rejectRefs.contains(ref)) {
        rejected++;
        results.add(ImportItemResult(
          index: i,
          externalRef: ref,
          action: 'rejected',
          reason: 'conflict',
        ));
      } else {
        created++;
        results.add(ImportItemResult(index: i, externalRef: ref, action: 'created'));
      }
    }
    return ImportResponse(
      dryRun: dryRun,
      created: created,
      updated: 0,
      rejected: rejected,
      results: results,
    );
  }
}

const String _header = 'external_ref,title,category,price_min,country';

Future<void> _pump(WidgetTester tester, _FakeRepo repo) async {
  await pumpApp(
    tester,
    logicalSize: const Size(540, 4500),
    location: '/my-products/import',
    overrides: [
      authProvider.overrideWith((ref) => _FixedAuth(ref, _verified)),
      myListingsRepositoryProvider.overrideWithValue(repo),
    ],
  );
}

Finder _key(String k) => find.byKey(ValueKey<String>(k));

void main() {
  setUpWidgetTests();

  testWidgets('import: validate rows, dry run, then import with per-row status', (tester) async {
    final repo = _FakeRepo(rejectRefs: {'B'});
    await _pump(tester, repo);
    expect(_key('imp-text'), findsOneWidget);
    expect(_key('imp-dry'), findsNothing);

    await tester.enterText(
      _key('imp-text'),
      '$_header\nA,مصباح LED,lighting,1.5,CN\nB,Panel Two,lighting,2,CN\nC,x,lighting,0,CN\n',
    );
    await settle(tester, frames: 2);

    // Live validation: row 4 is invalid and nothing was sent yet.
    expect(_key('imp-counts'), findsOneWidget);
    expect(_key('imp-status-4'), findsOneWidget);
    expect(find.text('غير صالح (لن يُرسل)'), findsOneWidget);
    expect(_key('imp-batches'), findsNothing);
    expect(repo.sizes, isEmpty);

    await tester.tap(_key('imp-dry'));
    await settle(tester, frames: 4);
    expect(repo.dryFlags, [true]);
    expect(repo.sizes, [2]);
    expect(_key('imp-summary'), findsOneWidget);
    expect(find.text('سيُنشأ'), findsOneWidget);
    expect(find.text('مرفوض'), findsOneWidget);
    expect(find.text('تعارض مع منتج موجود'), findsOneWidget);
    expect(_key('imp-status-4'), findsOneWidget);

    await tester.tap(_key('imp-run'));
    await settle(tester, frames: 4);
    expect(repo.dryFlags, [true, false]);
    expect(find.text('تم الإنشاء'), findsOneWidget);
    expect(find.text('سيُنشأ'), findsNothing);

    // Editing the text clears the stale results.
    await tester.enterText(_key('imp-text'), '$_header\nA,مصباح LED,lighting,1.5,CN\n');
    await settle(tester, frames: 2);
    expect(_key('imp-summary'), findsNothing);
    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });

  testWidgets('import: more than 100 rows are chunked and announced', (tester) async {
    final repo = _FakeRepo();
    await _pump(tester, repo);
    final b = StringBuffer('$_header\n');
    for (var i = 0; i < 250; i++) {
      b.writeln('r$i,Lamp $i,lighting,1,CN');
    }
    await tester.enterText(_key('imp-text'), b.toString());
    await settle(tester, frames: 2);
    expect(_key('imp-batches'), findsOneWidget);

    await tester.tap(_key('imp-run'));
    await settle(tester, frames: 6);
    expect(repo.sizes, [100, 100, 50]);
    expect(_key('imp-summary'), findsOneWidget);
    expect(_key('imp-run-error'), findsNothing);
    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });

  testWidgets('import: a failing batch shows partial results and an error', (tester) async {
    final repo = _FakeRepo(failOnCall: 2);
    await _pump(tester, repo);
    final b = StringBuffer('$_header\n');
    for (var i = 0; i < 150; i++) {
      b.writeln('r$i,Lamp $i,lighting,1,CN');
    }
    await tester.enterText(_key('imp-text'), b.toString());
    await settle(tester, frames: 2);
    await tester.tap(_key('imp-run'));
    await settle(tester, frames: 6);
    expect(repo.sizes, [100, 100]);
    expect(_key('imp-run-error'), findsOneWidget);
    expect(_key('imp-summary'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });

  testWidgets('import: missing columns and bad quotes show a message', (tester) async {
    final repo = _FakeRepo();
    await _pump(tester, repo);
    await tester.enterText(_key('imp-text'), 'external_ref,title\nA,Lamp');
    await settle(tester, frames: 2);
    expect(_key('imp-parse-error'), findsOneWidget);
    expect(_key('imp-run'), findsNothing);

    await tester.enterText(_key('imp-text'), '$_header\nA,"oops,lighting,1,CN');
    await settle(tester, frames: 2);
    expect(find.text('علامة اقتباس غير مغلقة. تأكد أن كل حقل بين علامتي اقتباس مغلق.'),
        findsOneWidget);
    await disposeApp(tester);
  });
}
