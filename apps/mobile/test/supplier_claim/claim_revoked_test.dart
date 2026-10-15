import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/core/i18n/error_messages.dart';
import 'package:factory_finder/features/my_products/my_products_logic.dart';
import 'package:factory_finder/features/trust/verification_models.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

const Me _verified = Me(
  id: 'u1',
  name: 'n',
  supplierId: 'sup_a',
  supplierClaimStatus: 'verified',
);
const Me _revoked = Me(id: 'u1', name: 'n');

class _FakeRepo extends AuthRepository {
  _FakeRepo() : super(ApiClient(baseUrl: 'http://unused.invalid', isMock: true));

  Me? next;
  Object? error;
  int calls = 0;

  @override
  Future<Me?> fetchMe() async {
    calls++;
    if (error != null) throw error!;
    return next;
  }
}

class _Auth extends AuthController {
  _Auth(Ref ref, Me? me) : super(ref) {
    state = me;
  }
}

ProviderContainer _container(_FakeRepo repo, Me? me) {
  final c = ProviderContainer(overrides: [
    authRepositoryProvider.overrideWithValue(repo),
    authProvider.overrideWith((ref) => _Auth(ref, me)),
  ]);
  addTearDown(c.dispose);
  return c;
}

void main() {
  test('supplierClaimWasRevoked only for verified -> none of the same user', () {
    expect(supplierClaimWasRevoked(_verified, _revoked), isTrue);
    expect(supplierClaimWasRevoked(null, _revoked), isFalse);
    expect(supplierClaimWasRevoked(_revoked, _revoked), isFalse);
    expect(supplierClaimWasRevoked(_verified, _verified), isFalse);
    const pending = Me(
        id: 'u1', name: 'n', supplierId: 'sup_a', supplierClaimStatus: 'pending');
    expect(supplierClaimWasRevoked(pending, _revoked), isFalse);
    expect(supplierClaimWasRevoked(_verified, const Me(id: 'u2', name: 'n')), isFalse);
  });

  test('Me.sameAs compares serialized fields', () {
    expect(_verified.sameAs(_verified.withSupplierId('sup_a', status: 'verified')), isTrue);
    expect(_verified.sameAs(_revoked), isFalse);
  });

  test('refreshMe: revoked claim updates the user and raises the notice', () async {
    final repo = _FakeRepo()..next = _revoked;
    final c = _container(repo, _verified);
    await c.read(authProvider.notifier).refreshMe();
    final me = c.read(authProvider)!;
    expect(me.supplierClaimStatus, 'none');
    expect(me.supplierId, isNull);
    expect(c.read(supplierClaimRevokedNoticeProvider), isTrue);
    // Dismissing clears it; the same state does not raise it again.
    c.read(supplierClaimRevokedNoticeProvider.notifier).state = false;
    await c.read(authProvider.notifier).refreshMe();
    expect(c.read(supplierClaimRevokedNoticeProvider), isFalse);
  });

  test('refreshMe: unchanged user keeps the same state object, no notice', () async {
    final repo = _FakeRepo()..next = _verified.withSupplierId('sup_a', status: 'verified');
    final c = _container(repo, _verified);
    await c.read(authProvider.notifier).refreshMe();
    expect(identical(c.read(authProvider), _verified), isTrue);
    expect(c.read(supplierClaimRevokedNoticeProvider), isFalse);
  });

  test('refreshMe: never-verified user going none does not raise the notice', () async {
    final repo = _FakeRepo()..next = _revoked;
    final c = _container(repo, const Me(id: 'u1', name: 'n', supplierId: 'sup_a', supplierClaimStatus: 'pending'));
    await c.read(authProvider.notifier).refreshMe();
    expect(c.read(authProvider)!.supplierClaimStatus, 'none');
    expect(c.read(supplierClaimRevokedNoticeProvider), isFalse);
  });

  test('refreshMe: errors, null (mock), signed out and other user are ignored', () async {
    final repo = _FakeRepo()
      ..error = ApiException(status: 500, code: 'server_error', message: 'x');
    final c = _container(repo, _verified);
    await c.read(authProvider.notifier).refreshMe();
    expect(identical(c.read(authProvider), _verified), isTrue);

    repo
      ..error = null
      ..next = null;
    await c.read(authProvider.notifier).refreshMe();
    expect(identical(c.read(authProvider), _verified), isTrue);

    repo.next = const Me(id: 'other', name: 'o');
    await c.read(authProvider.notifier).refreshMe();
    expect(identical(c.read(authProvider), _verified), isTrue);
    expect(c.read(supplierClaimRevokedNoticeProvider), isFalse);

    final signedOut = _FakeRepo()..next = _revoked;
    final c2 = _container(signedOut, null);
    await c2.read(authProvider.notifier).refreshMe();
    expect(signedOut.calls, 0);
  });

  test('refreshMe: minGap throttles repeated calls', () async {
    final repo = _FakeRepo()..next = _verified.withSupplierId('sup_a', status: 'verified');
    final c = _container(repo, _verified);
    final auth = c.read(authProvider.notifier);
    await auth.refreshMe(minGap: const Duration(minutes: 5));
    await auth.refreshMe(minGap: const Duration(minutes: 5));
    expect(repo.calls, 1);
    await auth.refreshMe();
    expect(repo.calls, 2);
  });

  test('logout clears the notice', () async {
    final repo = _FakeRepo()..next = _revoked;
    final c = _container(repo, _verified);
    await c.read(authProvider.notifier).refreshMe();
    expect(c.read(supplierClaimRevokedNoticeProvider), isTrue);
    c.read(authProvider.notifier).logout();
    expect(c.read(supplierClaimRevokedNoticeProvider), isFalse);
    expect(c.read(authProvider), isNull);
  });

  test('mock repository fetchMe returns null', () async {
    final repo = AuthRepository(ApiClient(baseUrl: 'http://x', isMock: true));
    expect(await repo.fetchMe(), isNull);
  });

  test('403 / 404 map to the supplier gate message keys', () {
    final e403 = ApiException(status: 403, code: 'forbidden', message: 'x');
    final e404 = ApiException(status: 404, code: 'not_found', message: 'x');
    final coded = ApiException(status: 400, code: 'supplier_claim_revoked', message: 'x');
    expect(isSupplierGateError(e403), isTrue);
    expect(isSupplierGateError(coded), isTrue);
    expect(isSupplierGateError(e404), isFalse);
    expect(isSupplierGateError(e404, notFoundCounts: true), isTrue);
    expect(isSupplierGateError(Exception('x'), notFoundCounts: true), isFalse);
    expect(myProductsErrorKey(e403), 'myp.err.supplier_required');
    expect(myProductsErrorKey(coded), 'myp.err.supplier_required');
    expect(verificationErrorKey(e403), 'ver.err.supplier_required');
    expect(verificationErrorKey(coded), 'ver.err.supplier_required');
  });
}
