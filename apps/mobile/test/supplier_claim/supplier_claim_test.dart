import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/api/auth.dart';
import 'package:factory_finder/features/supplier_claim/supplier_claim_logic.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('Me parses supplier_id, tolerant of missing/null', () {
    expect(Me.fromJson({'id': 'u', 'name': 'n'}).supplierId, isNull);
    expect(Me.fromJson({'id': 'u', 'name': 'n', 'supplier_id': null}).supplierId, isNull);
    final me = Me.fromJson({'id': 'u', 'name': 'n', 'supplier_id': 'sup_abc'});
    expect(me.supplierId, 'sup_abc');
    expect(me.toJson()['supplier_id'], 'sup_abc');
    expect(me.withSupplierId(null).supplierId, isNull);
    expect(me.withSupplierId(null).name, 'n');
  });

  test('Me parses supplier_claim_status, tolerant of missing field', () {
    expect(Me.fromJson({'id': 'u', 'name': 'n'}).supplierClaimStatus, 'none');
    expect(
        Me.fromJson({'id': 'u', 'name': 'n', 'supplier_id': 'sup_a'}).supplierClaimStatus,
        'verified');
    final p = Me.fromJson({
      'id': 'u',
      'name': 'n',
      'supplier_id': 'sup_a',
      'supplier_claim_status': 'pending'
    });
    expect(p.supplierClaimStatus, 'pending');
    expect(p.withSupplierId(null).supplierClaimStatus, 'none');
  });

  test('supplier id validation', () {
    expect(isValidSupplierId('sup_abc_1'), true);
    expect(isValidSupplierId(' sup_abc '), true);
    expect(isValidSupplierId('sup_'), false);
    expect(isValidSupplierId('abc'), false);
    expect(isValidSupplierId('sup_a-b'), false);
    expect(supplierIdErrorKey('x'), 'claim.err.format');
    expect(supplierIdErrorKey('sup_x'), isNull);
  });

  test('mock repo claim, release and 409', () async {
    final repo = AuthRepository(ApiClient(baseUrl: 'http://x', isMock: true));
    const me = Me(id: kMockUserId, name: 'm');
    final claimed = await repo.claimSupplier(me, 'sup_ok');
    expect(claimed.supplierId, 'sup_ok');
    expect(claimed.supplierClaimStatus, 'pending');
    final released = await repo.claimSupplier(claimed, null);
    expect(released.supplierId, isNull);
    try {
      await repo.claimSupplier(me, kMockTakenSupplierId);
      fail('expected ApiException');
    } on ApiException catch (e) {
      expect(e.status, 409);
      expect(e.code, 'supplier_claimed');
      expect(claimErrorKey(e), 'claim.err.taken');
    }
    expect(claimErrorKey(Exception('x')), 'claim.err.generic');
  });
}
