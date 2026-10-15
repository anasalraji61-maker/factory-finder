import 'package:factory_finder/core/api/auth.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'test_app.dart';

class _FixedAuth extends AuthController {
  _FixedAuth(Ref ref, Me me) : super(ref) {
    state = me;
  }
}

void main() {
  setUpWidgetTests();

  testWidgets('profile shows the revoked-claim notice once and it can be dismissed',
      (tester) async {
    await pumpApp(
      tester,
      location: '/profile',
      overrides: [
        authProvider.overrideWith((ref) => _FixedAuth(ref, const Me(id: 'u', name: 'N'))),
        supplierClaimRevokedNoticeProvider.overrideWith((ref) => true),
      ],
    );
    expect(find.byKey(const ValueKey('profile-claim-revoked')), findsOneWidget);
    expect(find.byKey(const ValueKey('profile-my-products')), findsNothing);

    await tester.tap(find.byKey(const ValueKey('profile-claim-revoked-dismiss')));
    await settle(tester, frames: 3);
    expect(find.byKey(const ValueKey('profile-claim-revoked')), findsNothing);
    expect(tester.takeException(), isNull);
    await disposeApp(tester);
  });
}
