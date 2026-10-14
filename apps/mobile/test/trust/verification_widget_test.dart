import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/core/storage/key_value_store.dart';
import 'package:factory_finder/features/my_products/media/image_pick_service.dart';
import 'package:factory_finder/features/my_products/media/media_repository.dart';
import 'package:factory_finder/features/my_products/screens/my_products_screen.dart';
import 'package:factory_finder/features/trust/verification_badge.dart';
import 'package:factory_finder/features/trust/verification_models.dart';
import 'package:factory_finder/features/trust/verification_repository.dart';
import 'package:factory_finder/features/trust/verification_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../widgets/test_app.dart';

dynamic _load(String name) =>
    jsonDecode(File('test/fixtures/live/$name.json').readAsStringSync());

class _FakeRepo implements VerificationRepository {
  VerificationList list = VerificationList.fromJson(_load('verification_documents'));
  final List<VerificationDraft> submitted = [];
  final List<String> withdrawn = [];
  Object? submitError;
  Object? withdrawError;
  Object? badgeError;
  String badgeLevel = 'documented';

  @override
  Future<VerificationList> listMine() async => list;

  @override
  Future<VerificationDocument> submit(VerificationDraft draft) async {
    final err = submitError;
    if (err != null) throw err;
    submitted.add(draft);
    return VerificationDocument.fromJson(_load('verification_document_created'));
  }

  @override
  Future<VerificationDocument> withdraw(String documentId) async {
    final err = withdrawError;
    if (err != null) throw err;
    withdrawn.add(documentId);
    return VerificationDocument.fromJson(_load('verification_document_created'));
  }

  @override
  Future<PublicVerification> publicBadge(String supplierId) async {
    final err = badgeError;
    if (err != null) throw err;
    return PublicVerification(supplierId: supplierId, level: badgeLevel);
  }
}

class _FixedAuth extends AuthController {
  _FixedAuth(Ref ref, Me me) : super(ref) {
    state = me;
  }
}

Future<void> _pump(
  WidgetTester tester,
  Widget home, {
  List<Override> overrides = const [],
  double scale = 1.0,
  Locale locale = const Locale('en'),
}) async {
  tester.view.physicalSize = const Size(360, 3000);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        keyValueStoreProvider.overrideWithValue(MemoryStore()),
        secureStoreProvider.overrideWithValue(MemoryStore()),
        ...overrides,
      ],
      child: MaterialApp(
        locale: locale,
        supportedLocales: const [Locale('ar'), Locale('en')],
        localizationsDelegates: GlobalMaterialLocalizations.delegates,
        builder: (context, child) => MediaQuery(
          data: MediaQuery.of(context).copyWith(textScaler: TextScaler.linear(scale)),
          child: child!,
        ),
        home: home,
      ),
    ),
  );
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 100));
}

Future<void> _openSheet(WidgetTester tester) async {
  await tester.tap(find.byKey(const ValueKey<String>('ver-add')));
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 400));
  expect(find.byKey(const ValueKey<String>('ver-form')), findsOneWidget);
}

void _selectType(WidgetTester tester, String type) {
  tester
      .widget<ChoiceChip>(find.byKey(ValueKey<String>('ver-type-$type')))
      .onSelected!(true);
}

PickedImage _png({int bytes = 3}) => PickedImage(
      bytes: Uint8List(bytes)..fillRange(0, bytes, 1),
      filename: 'doc.png',
      mime: 'image/png',
    );

String _en(String key, [Map<String, String> args = const {}]) =>
    AppStrings.lookup('en', key, args);

void main() {
  setUpWidgetTests();

  final bypass = myProductsBypassGateProvider.overrideWithValue(true);

  testWidgets('lists documents with status chips, masked numbers and reasons',
      (tester) async {
    final repo = _FakeRepo();
    await _pump(tester, const VerificationScreen(), overrides: [
      bypass,
      verificationRepositoryProvider.overrideWithValue(repo),
    ]);

    Finder status(String id, String text) => find.descendant(
          of: find.byKey(ValueKey<String>('ver-status-$id')),
          matching: find.text(text),
        );
    expect(status('vdoc_0001', 'Approved'), findsOneWidget);
    expect(status('vdoc_0002', 'Rejected'), findsOneWidget);
    expect(status('vdoc_0003', 'Expired'), findsOneWidget);
    expect(status('vdoc_0004', 'Pending'), findsOneWidget);
    expect(find.text('Number: ****5678'), findsOneWidget);
    expect(find.text('Number: ****9001'), findsOneWidget);
    expect(find.byKey(const ValueKey<String>('ver-number-vdoc_0004')), findsNothing);
    expect(find.text('Rejection reason: The document is not legible'), findsOneWidget);
    expect(find.byKey(const ValueKey<String>('ver-badge-basic')), findsOneWidget);
    expect(find.byKey(const ValueKey<String>('ver-withdraw-vdoc_0001')), findsOneWidget);
    expect(find.byKey(const ValueKey<String>('ver-withdraw-vdoc_0004')), findsOneWidget);
    expect(find.byKey(const ValueKey<String>('ver-withdraw-vdoc_0002')), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('empty list and level none', (tester) async {
    final repo = _FakeRepo()..list = const VerificationList(items: [], level: 'none');
    await _pump(tester, const VerificationScreen(), overrides: [
      bypass,
      verificationRepositoryProvider.overrideWithValue(repo),
    ]);
    expect(find.byKey(const ValueKey<String>('ver-empty')), findsOneWidget);
    expect(find.byKey(const ValueKey<String>('ver-level-none')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('Arabic labels render', (tester) async {
    final repo = _FakeRepo();
    await _pump(
      tester,
      const VerificationScreen(),
      locale: const Locale('ar'),
      overrides: [bypass, verificationRepositoryProvider.overrideWithValue(repo)],
    );
    expect(find.text(AppStrings.lookup('ar', 'ver.status.approved')), findsOneWidget);
    expect(find.text(AppStrings.lookup('ar', 'ver.type.business_license')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('screen and form survive text scale 2.0', (tester) async {
    final repo = _FakeRepo();
    await _pump(tester, const VerificationScreen(), scale: 2.0, overrides: [
      bypass,
      verificationRepositoryProvider.overrideWithValue(repo),
    ]);
    expect(tester.takeException(), isNull);
    await _openSheet(tester);
    _selectType(tester, 'company_registry_reference');
    await tester.pump();
    expect(tester.takeException(), isNull);
  });

  testWidgets('gate: sign-in hint and unverified supplier card', (tester) async {
    await _pump(tester, const VerificationScreen(), overrides: [
      myProductsBypassGateProvider.overrideWithValue(false),
      verificationRepositoryProvider.overrideWithValue(_FakeRepo()),
    ]);
    expect(find.text(_en('ver.signin')), findsOneWidget);
    expect(find.byKey(const ValueKey<String>('ver-gate-card')), findsNothing);
  });

  testWidgets('gate: pending claim sees the link-account card', (tester) async {
    const me = Me(
      id: 'usr_s',
      name: 'S',
      supplierId: 'sup_iq_001',
      supplierClaimStatus: 'pending',
    );
    await _pump(tester, const VerificationScreen(), overrides: [
      myProductsBypassGateProvider.overrideWithValue(false),
      authProvider.overrideWith((ref) => _FixedAuth(ref, me)),
      verificationRepositoryProvider.overrideWithValue(_FakeRepo()),
    ]);
    expect(find.byKey(const ValueKey<String>('ver-gate-card')), findsOneWidget);
    expect(find.byKey(const ValueKey<String>('ver-add')), findsNothing);
  });

  testWidgets('withdraw asks for confirmation and calls the repository', (tester) async {
    final repo = _FakeRepo();
    await _pump(tester, const VerificationScreen(), overrides: [
      bypass,
      verificationRepositoryProvider.overrideWithValue(repo),
    ]);
    await tester.tap(find.byKey(const ValueKey<String>('ver-withdraw-vdoc_0004')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));

    // Cancel keeps the document.
    await tester.tap(find.byKey(const ValueKey<String>('ver-withdraw-cancel')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    expect(repo.withdrawn, isEmpty);

    await tester.tap(find.byKey(const ValueKey<String>('ver-withdraw-vdoc_0004')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    await tester.tap(find.byKey(const ValueKey<String>('ver-withdraw-confirm')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    expect(repo.withdrawn, ['vdoc_0004']);
    expect(find.text(_en('ver.withdraw_ok')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('withdraw conflict shows a mapped error', (tester) async {
    final repo = _FakeRepo()
      ..withdrawError =
          ApiException(status: 409, code: 'invalid_transition', message: 'x');
    await _pump(tester, const VerificationScreen(), overrides: [
      bypass,
      verificationRepositoryProvider.overrideWithValue(repo),
    ]);
    await tester.tap(find.byKey(const ValueKey<String>('ver-withdraw-vdoc_0001')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    await tester.tap(find.byKey(const ValueKey<String>('ver-withdraw-confirm')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.text(_en('ver.err.transition')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('submit form validates on the client before calling the repository',
      (tester) async {
    final repo = _FakeRepo();
    await _pump(tester, const VerificationScreen(), overrides: [
      bypass,
      verificationRepositoryProvider.overrideWithValue(repo),
    ]);
    await _openSheet(tester);
    await tester.tap(find.byKey(const ValueKey<String>('ver-submit')));
    await tester.pump();
    expect(find.text(_en('ver.err.type')), findsOneWidget);
    expect(find.text(_en('ver.err.country')), findsOneWidget);
    expect(find.text(_en('ver.err.number')), findsOneWidget);
    expect(find.text(_en('ver.err.files')), findsOneWidget);
    expect(find.text(_en('ver.err.consent')), findsOneWidget);
    expect(repo.submitted, isEmpty);

    // A past expiry date is rejected too.
    _selectType(tester, 'export_license');
    await tester.pump();
    await tester.enterText(find.byKey(const ValueKey<String>('ver-expiry')), '2020-01-01');
    await tester.tap(find.byKey(const ValueKey<String>('ver-submit')));
    await tester.pump();
    expect(find.text(_en('ver.err.expiry_past')), findsOneWidget);
    expect(find.text(_en('ver.err.type')), findsNothing);
    expect(repo.submitted, isEmpty);
  });

  testWidgets('submit form uploads an image and sends the document', (tester) async {
    final repo = _FakeRepo();
    final picker = FakeImagePickService();
    await _pump(tester, const VerificationScreen(), overrides: [
      bypass,
      verificationRepositoryProvider.overrideWithValue(repo),
      imagePickServiceProvider.overrideWithValue(picker),
      mediaRepositoryProvider.overrideWithValue(MockMediaRepository()),
    ]);
    await _openSheet(tester);

    _selectType(tester, 'business_license');
    await tester.pump();
    await tester.enterText(find.byKey(const ValueKey<String>('ver-country')), 'iq');
    await tester.enterText(find.byKey(const ValueKey<String>('ver-number')), 'LIC-12345');
    await tester.enterText(find.byKey(const ValueKey<String>('ver-expiry')), '2031-01-31');

    // Oversized file is refused client-side.
    picker.next = _png(bytes: 5 * 1024 * 1024 + 1);
    await tester.tap(find.byKey(const ValueKey<String>('ver-gallery')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    expect(find.text(_en('myp.media.err.too_large')), findsOneWidget);
    expect(find.byKey(const ValueKey<String>('ver-file-0')), findsNothing);

    picker.next = _png();
    await tester.tap(find.byKey(const ValueKey<String>('ver-gallery')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.byKey(const ValueKey<String>('ver-file-0')), findsOneWidget);
    expect(find.text(_en('myp.media.err.too_large')), findsNothing);
    expect(picker.galleryCalls, 2);

    // Remove then re-add.
    tester
        .widget<InputChip>(find.byKey(const ValueKey<String>('ver-file-0')))
        .onDeleted!();
    await tester.pump();
    expect(find.byKey(const ValueKey<String>('ver-file-0')), findsNothing);
    await tester.tap(find.byKey(const ValueKey<String>('ver-gallery')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.byKey(const ValueKey<String>('ver-file-0')), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey<String>('ver-consent')));
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey<String>('ver-submit')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));

    expect(repo.submitted, hasLength(1));
    final body = repo.submitted.single.toJson();
    expect(body['doc_type'], 'business_license');
    expect(body['issuing_country'], 'IQ');
    expect(body['number'], 'LIC-12345');
    expect(body['expires_on'], '2031-01-31');
    expect(body['consent'], true);
    final files = body['files'] as List;
    expect(files, hasLength(1));
    expect((files.single as String).startsWith('/v1/media/files/'), isTrue);
    // Sheet closed, snackbar shown.
    expect(find.byKey(const ValueKey<String>('ver-form')), findsNothing);
    expect(find.text(_en('ver.submit_ok')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('rate limit (429) keeps the sheet open with a wait hint', (tester) async {
    final repo = _FakeRepo()
      ..submitError = ApiException(
        status: 429,
        code: 'rate_limited',
        message: 'slow',
        retryAfterSeconds: 125,
      );
    final picker = FakeImagePickService(next: _png());
    await _pump(tester, const VerificationScreen(), overrides: [
      bypass,
      verificationRepositoryProvider.overrideWithValue(repo),
      imagePickServiceProvider.overrideWithValue(picker),
      mediaRepositoryProvider.overrideWithValue(MockMediaRepository()),
    ]);
    await _openSheet(tester);
    _selectType(tester, 'iso_certificate');
    await tester.pump();
    await tester.enterText(find.byKey(const ValueKey<String>('ver-country')), 'CN');
    await tester.enterText(find.byKey(const ValueKey<String>('ver-number')), 'ISO-9001-X');
    await tester.tap(find.byKey(const ValueKey<String>('ver-gallery')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));
    await tester.tap(find.byKey(const ValueKey<String>('ver-consent')));
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey<String>('ver-submit')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));

    expect(find.byKey(const ValueKey<String>('ver-form')), findsOneWidget);
    expect(find.text(_en('ver.err.rate_limited_wait', {'n': '3'})), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('factory photos hide the number field', (tester) async {
    final repo = _FakeRepo();
    await _pump(tester, const VerificationScreen(), overrides: [
      bypass,
      verificationRepositoryProvider.overrideWithValue(repo),
    ]);
    await _openSheet(tester);
    expect(find.byKey(const ValueKey<String>('ver-number')), findsOneWidget);
    _selectType(tester, 'factory_photos');
    await tester.pump();
    expect(find.byKey(const ValueKey<String>('ver-number')), findsNothing);
    expect(find.byKey(const ValueKey<String>('ver-number-none')), findsOneWidget);
  });

  group('public badge', () {
    Future<void> pumpBadge(WidgetTester tester, _FakeRepo repo) => _pump(
          tester,
          const Scaffold(body: SupplierVerificationBadge(supplierId: 'sup_cn_018')),
          overrides: [verificationRepositoryProvider.overrideWithValue(repo)],
        );

    testWidgets('shows the level', (tester) async {
      await pumpBadge(tester, _FakeRepo()..badgeLevel = 'audited');
      expect(find.byKey(const ValueKey<String>('ver-badge-audited')), findsOneWidget);
      expect(find.text(_en('ver.badge.audited')), findsOneWidget);
    });

    testWidgets('level none renders nothing', (tester) async {
      await pumpBadge(tester, _FakeRepo()..badgeLevel = 'none');
      expect(find.byType(VerificationLevelChip), findsNothing);
    });

    testWidgets('missing endpoint (404) falls back silently', (tester) async {
      await pumpBadge(
        tester,
        _FakeRepo()
          ..badgeError = ApiException(status: 404, code: 'not_found', message: 'x'),
      );
      expect(find.byType(VerificationLevelChip), findsNothing);
      expect(tester.takeException(), isNull);
    });
  });

  testWidgets('supplier screen shows the verification badge next to trust',
      (tester) async {
    final repo = _FakeRepo()..badgeLevel = 'documented';
    await pumpApp(
      tester,
      location: '/supplier/sup_cn_004',
      overrides: [verificationRepositoryProvider.overrideWithValue(repo)],
    );
    await settle(tester, frames: 8);
    expect(find.byKey(const ValueKey<String>('ver-badge-documented')), findsOneWidget);
    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });

  testWidgets('supplier screen still renders when the badge endpoint fails',
      (tester) async {
    final repo = _FakeRepo()
      ..badgeError = ApiException(status: 503, code: 'http_503', message: 'down');
    await pumpApp(
      tester,
      location: '/supplier/sup_cn_004',
      overrides: [verificationRepositoryProvider.overrideWithValue(repo)],
    );
    await settle(tester, frames: 8);
    expect(find.byType(VerificationLevelChip), findsNothing);
    expect(find.byKey(const Key('trust_report_button')), findsOneWidget);
    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });

  testWidgets('the /verification route opens the screen with mock data', (tester) async {
    await pumpApp(tester, location: '/verification');
    await settle(tester, frames: 6);
    expect(find.byKey(const ValueKey<String>('ver-doc-vdoc_mock_1')), findsOneWidget);
    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });
}
