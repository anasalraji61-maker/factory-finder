import 'dart:convert';

import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/widgets/widgets.dart';
import 'package:factory_finder/features/requests/data/mock_rfq.dart';
import 'package:factory_finder/features/requests/data/rfq_models.dart';
import 'package:factory_finder/features/requests/data/rfq_repository.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../widgets/test_app.dart';

RfqDraft _draft(List<String> invites) => RfqDraft(
      kind: ListingKind.product,
      title: 'Solar lights',
      quantity: '10',
      unit: 'piece',
      destination: const Location(countryCode: 'IQ', city: 'Baghdad'),
      invitedSupplierIds: invites,
    );

Map<String, dynamic> _requestJson(Map<String, dynamic> extra) => {
      'id': 'req_x',
      'owner_id': 'usr_1',
      'title': 'T',
      'kind': 'product',
      'quantity': '1',
      'status': 'open',
      'created_at': '2026-10-15T00:00:00Z',
      ...extra,
    };

void main() {
  group('invite models', () {
    test('draft sends invited_supplier_ids only when non-empty', () {
      expect(_draft(const <String>[]).toJson().containsKey('invited_supplier_ids'), isFalse);
      expect(_draft(const ['sup_1', 'sup_2']).toJson()['invited_supplier_ids'],
          ['sup_1', 'sup_2']);
    });

    test('request parses and echoes invited_supplier_ids', () {
      final r = RfqRequest.fromJson(_requestJson({
        'invited_supplier_ids': ['sup_1', 'sup_1', 'sup_2'],
      }));
      expect(r.invitedSupplierIds, ['sup_1', 'sup_2']);
      expect(r.isInviteOnly, isTrue);
      final json = jsonDecode(jsonEncode(r.toJson())) as Map<String, dynamic>;
      expect(json['invited_supplier_ids'], ['sup_1', 'sup_2']);
      expect(RfqRequest.fromJson(json).copyWith(offerCount: 2).isInviteOnly, isTrue);
    });

    test('request without the field is not invite-only', () {
      final r = RfqRequest.fromJson(_requestJson({}));
      expect(r.isInviteOnly, isFalse);
      expect(r.toJson().containsKey('invited_supplier_ids'), isFalse);
    });

    test('id validation matches the contract pattern', () {
      expect(isValidInviteId('sup_cn_001'), isTrue);
      expect(isValidInviteId('a.b:c-d'), isTrue);
      expect(isValidInviteId(''), isFalse);
      expect(isValidInviteId('has space'), isFalse);
      expect(isValidInviteId('x' * 65), isFalse);
      expect(kRfqMaxInvites, 50);
    });

    test('mock repository stores invites on created requests', () async {
      final backend = MockRfqBackend();
      final repo = RfqRepository(
        ApiClient(baseUrl: 'http://fake', isMock: true),
        backend,
      );
      final created = await repo.create(_draft(const ['sup_cn_001']));
      expect(created.invitedSupplierIds, ['sup_cn_001']);
      final fetched = await repo.get(created.id);
      expect(fetched.isInviteOnly, isTrue);
    });
  });

  group('invite flow', () {
    testWidgets('supplier page offers a request-a-quote action', (tester) async {
      tester.view.physicalSize = const Size(1080, 4800);
      tester.view.devicePixelRatio = 3.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await pumpApp(tester, location: '/supplier/sup_cn_001');
      await settle(tester, frames: 8);
      final cta = find.byKey(const ValueKey<String>('supplier-request-quote'));
      expect(cta, findsOneWidget);
      expect(tester.widget<OutlinedButton>(cta).onPressed, isNotNull);
      await disposeApp(tester);
    });

    testWidgets('chip is removable and invites are sent on submit', (tester) async {
      tester.view.physicalSize = const Size(1080, 4800);
      tester.view.devicePixelRatio = 3.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final backend = MockRfqBackend();
      final repo = RfqRepository(
        ApiClient(baseUrl: 'http://fake', isMock: true),
        backend,
      );
      await pumpApp(
        tester,
        location: '/requests/new?supplier=sup_cn_001&supplier_name=Shenzhen%20Co',
        overrides: [rfqRepositoryProvider.overrideWithValue(repo)],
      );
      expect(find.text('Shenzhen Co'), findsOneWidget);
      await tester.enterText(find.byType(TextFormField).first, 'LED street lights');
      final submit = find.byType(PrimaryButton);
      await tester.ensureVisible(submit);
      await tester.tap(submit);
      await settle(tester, frames: 12);
      expect(backend.requests.first.title, 'LED street lights');
      expect(backend.requests.first.invitedSupplierIds, ['sup_cn_001']);
      await disposeApp(tester);
    });

    testWidgets('removing the chip hides the list and sends no invites',
        (tester) async {
      tester.view.physicalSize = const Size(1080, 4800);
      tester.view.devicePixelRatio = 3.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await pumpApp(tester, location: '/requests/new?supplier=sup_cn_001');
      final chip = find.byKey(const ValueKey<String>('req-invite-sup_cn_001'));
      expect(chip, findsOneWidget);
      await tester.ensureVisible(chip);
      await tester.tap(find.descendant(of: chip, matching: find.byIcon(Icons.cancel)));
      await settle(tester);
      expect(chip, findsNothing);
      expect(find.byKey(const ValueKey<String>('req-invite-count')), findsNothing);
      await disposeApp(tester);
    });

    testWidgets('invalid supplier query is ignored', (tester) async {
      tester.view.physicalSize = const Size(1080, 4800);
      tester.view.devicePixelRatio = 3.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await pumpApp(tester, location: '/requests/new?supplier=bad%20id');
      expect(find.byKey(const ValueKey<String>('req-invite-count')), findsNothing);
      await disposeApp(tester);
    });

    testWidgets('detail shows the Invite-only pill for invite-only requests',
        (tester) async {
      tester.view.physicalSize = const Size(1080, 4800);
      tester.view.devicePixelRatio = 3.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final backend = MockRfqBackend();
      final created = backend.create(_draft(const ['sup_cn_001']));
      final repo = RfqRepository(
        ApiClient(baseUrl: 'http://fake', isMock: true),
        backend,
      );
      await pumpApp(
        tester,
        location: '/requests/${created.id}',
        overrides: [rfqRepositoryProvider.overrideWithValue(repo)],
      );
      expect(find.byKey(const ValueKey<String>('req-invite-only-pill')), findsOneWidget);
      await disposeApp(tester);
    });
  });
}
