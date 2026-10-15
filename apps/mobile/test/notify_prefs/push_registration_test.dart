import 'dart:async';

import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/features/notify_prefs/notify_prefs_models.dart';
import 'package:factory_finder/features/notify_prefs/push_registration.dart';
import 'package:factory_finder/features/watchlist/data/watch_models.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../widgets/test_app.dart';

class _FakeSource implements PushTokenSource {
  _FakeSource({this.perm = PushPermission.unknown, this.grantOnRequest = true});
  PushPermission perm;
  final bool grantOnRequest;
  String? tok = 'tok_1';
  int requests = 0;
  int deleted = 0;
  final StreamController<String> refresh = StreamController<String>.broadcast();

  @override
  String get platform => 'android';
  @override
  Future<PushPermission> permission() async => perm;
  @override
  Future<PushPermission> requestPermission() async {
    requests++;
    perm = grantOnRequest ? PushPermission.granted : PushPermission.denied;
    return perm;
  }

  @override
  Future<String?> token() async => tok;
  @override
  Future<void> deleteToken() async {
    deleted++;
    tok = null;
  }

  @override
  Stream<String> get onTokenRefresh => refresh.stream;
}

class _Repo extends MockDeviceRepository {
  bool failUnregister = false;
  int? unregisterStatus;
  Completer<void>? gate;

  @override
  Future<String> register({
    required String platform,
    required String token,
    required String locale,
  }) async {
    await gate?.future;
    return super.register(platform: platform, token: token, locale: locale);
  }

  @override
  Future<void> unregister(String deviceId) async {
    if (failUnregister) {
      throw ApiException(status: unregisterStatus ?? 500, code: 'x', message: 'x');
    }
    return super.unregister(deviceId);
  }
}

Future<void> _pump() => Future<void>.delayed(Duration.zero);

void main() {
  group('push token lifecycle', () {
    test('login registers; logout unregisters server-side and deletes token', () async {
      final src = _FakeSource();
      final repo = _Repo();
      final c = PushRegistrationController(src, repo);
      expect(await c.onLogin(), PushPermission.granted);
      expect(src.requests, 1);
      expect(repo.devices.values, ['tok_1']);
      expect(c.isRegistered, isTrue);

      await c.onLogout();
      expect(repo.devices, isEmpty);
      expect(c.isRegistered, isFalse);
      expect(src.deleted, 1);
    });

    test('denied permission registers nothing', () async {
      final src = _FakeSource(grantOnRequest: false);
      final repo = _Repo();
      final c = PushRegistrationController(src, repo);
      expect(await c.onLogin(), PushPermission.denied);
      expect(repo.devices, isEmpty);
      expect(c.permission, PushPermission.denied);
    });

    test('prompt=false never shows the OS dialog', () async {
      final src = _FakeSource();
      final c = PushRegistrationController(src, _Repo());
      await c.onLogin(prompt: false);
      expect(src.requests, 0);
      expect(c.isRegistered, isFalse);
    });

    test('previously granted permission skips the prompt', () async {
      final src = _FakeSource(perm: PushPermission.granted);
      final c = PushRegistrationController(src, _Repo());
      await c.onLogin();
      expect(src.requests, 0);
      expect(c.isRegistered, isTrue);
    });

    test('token refresh re-registers; same token is not re-sent', () async {
      final src = _FakeSource();
      final repo = _Repo();
      final c = PushRegistrationController(src, repo);
      await c.onLogin();
      src.refresh.add('tok_1');
      await _pump();
      expect(repo.devices.length, 1);
      src.refresh.add('tok_2');
      await _pump();
      expect(repo.devices.values, ['tok_2']);
    });

    test('logout still deletes local token when the server call fails', () async {
      final src = _FakeSource();
      final repo = _Repo();
      final c = PushRegistrationController(src, repo);
      await c.onLogin();
      repo.failUnregister = true;
      await c.onLogout();
      expect(src.deleted, 1);
      expect(c.isRegistered, isFalse);
    });

    test('logout after refresh listener cancelled ignores later refreshes', () async {
      final src = _FakeSource();
      final repo = _Repo();
      final c = PushRegistrationController(src, repo);
      await c.onLogin();
      await c.onLogout();
      src.refresh.add('tok_late');
      await _pump();
      expect(repo.devices, isEmpty);
    });

    test('registration in flight during logout is undone', () async {
      final src = _FakeSource();
      final repo = _Repo()..gate = Completer<void>();
      final c = PushRegistrationController(src, repo);
      final login = c.onLogin();
      await _pump();
      final logout = c.onLogout();
      repo.gate!.complete();
      await login;
      await logout;
      await _pump();
      expect(repo.devices, isEmpty);
      expect(c.isRegistered, isFalse);
    });

    test('404 on unregister counts as already gone', () async {
      final src = _FakeSource();
      final repo = _Repo();
      final c = PushRegistrationController(src, repo);
      await c.onLogin();
      repo.failUnregister = true;
      repo.unregisterStatus = 404;
      await c.onLogout();
      expect(c.deviceId, isNull);
    });

    test('Noop source never registers', () async {
      final repo = _Repo();
      final c = PushRegistrationController(NoopPushTokenSource(), repo);
      await c.onLogin();
      expect(repo.devices, isEmpty);
    });
  });

  group('alert deep links', () {
    test('isSafeRouteId accepts opaque ids, rejects path tricks', () {
      for (final ok in ['lst_0041', 'alibaba:123', 'a-b.c', '7']) {
        expect(isSafeRouteId(ok), isTrue, reason: ok);
      }
      for (final bad in [
        '', '..', '../admin', 'a/b', 'a?x=1', 'a#f', ' a', 'a b', '/x',
        'https://evil.test', '%2e%2e', 'a..b', '.hidden',
      ]) {
        expect(isSafeRouteId(bad), isFalse, reason: bad);
      }
      expect(isSafeRouteId(null), isFalse);
    });

    test('PriceAlert.listingRoute is validated and internal', () {
      PriceAlert a(Object? ids) => PriceAlert.fromJson({
            'id': 'a',
            'payload': {'listing_ids': ids},
          });
      expect(a(['lst_1']).listingRoute, '/listing/lst_1');
      expect(a([42]).listingRoute, '/listing/42');
      expect(a(['../../settings']).listingRoute, isNull);
      expect(a(['x/y']).listingRoute, isNull);
      expect(a([null]).listingRoute, isNull);
      expect(a([{'a': 1}]).listingRoute, isNull);
      expect(a([]).listingRoute, isNull);
      expect(a('nope').listingRoute, isNull);
    });

    test('unsafe shipment id gives no tracking route', () {
      final a = PriceAlert.fromJson({
        'id': 'a',
        'rule': 'shipment_status',
        'payload': {
          'shipment': {'shipment_id': '../x'}
        },
      });
      expect(a.trackingRoute, isNull);
    });
  });

  group('prefs model', () {
    test('quiet hours round trip and clear', () {
      final p = NotifyPrefs.fromJson({
        'quiet_hours': {'start': '22:00', 'end': '07:00'},
        'timezone': 'Asia/Dubai',
      });
      expect(p.toUpdateJson()['quiet_hours'], {'start': '22:00', 'end': '07:00'});
      final cleared = p.copyWith(clearQuiet: true).toUpdateJson();
      expect(cleared.containsKey('quiet_hours'), isFalse);
      expect(cleared['clear_quiet_hours'], isTrue);
      expect(cleared['timezone'], 'Asia/Dubai');
    });

    test('half-set or malformed quiet hours are dropped', () {
      expect(NotifyPrefs.fromJson({'quiet_hours': {'start': '25:00', 'end': '07:00'}}).hasQuietHours, isFalse);
      expect(NotifyPrefs.fromJson({'quiet_hours': {'start': '22:00'}}).hasQuietHours, isFalse);
    });

    test('per-rule toggle only touches its rule/channel', () {
      final p = const NotifyPrefs().withChannel('price_drop', 'push', true);
      expect(p.isOn('price_drop', 'push'), isTrue);
      expect(p.isOn('below_target', 'push'), isFalse);
      expect(p.withChannel('price_drop', 'push', false).isOn('price_drop', 'push'), isFalse);
    });
  });

  group('prefs screen', () {
    setUpWidgetTests();

    testWidgets('shows quiet-hours summary with timezone', (tester) async {
      await pumpApp(tester, location: '/notification-prefs', logicalSize: const Size(540, 3200));
      await settle(tester, frames: 8);
      expect(find.byKey(const Key('np_quiet_summary')), findsOneWidget);
      expect(find.textContaining('Asia/Baghdad'), findsWidgets);
    });

    testWidgets('denied push permission shows the banner', (tester) async {
      await pumpApp(
        tester,
        location: '/notification-prefs',
        logicalSize: const Size(540, 3200),
        overrides: [pushPermissionProvider.overrideWith((ref) => PushPermission.denied)],
      );
      await settle(tester, frames: 8);
      expect(find.byKey(const Key('np_push_denied')), findsOneWidget);
    });

    testWidgets('no banner when permission is unknown', (tester) async {
      await pumpApp(tester, location: '/notification-prefs', logicalSize: const Size(540, 3200));
      await settle(tester, frames: 8);
      expect(find.byKey(const Key('np_push_denied')), findsNothing);
    });
  });
}
