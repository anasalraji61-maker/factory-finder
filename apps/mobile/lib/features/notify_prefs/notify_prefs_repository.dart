import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/features/notify_prefs/notify_prefs_models.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

abstract class NotifyPrefsRepository {
  Future<NotifyPrefs> get();

  /// [digestEmail]: null = untouched, '' = clear, else a new pending address.
  Future<NotifyPrefs> save(NotifyPrefs prefs, {String? digestEmail});
  Future<NotifyPrefs> verifyEmail(String code);
  Future<NotifyPrefs> resendCode();
}

class LiveNotifyPrefsRepository implements NotifyPrefsRepository {
  LiveNotifyPrefsRepository(this._api);
  final ApiClient _api;

  @override
  Future<NotifyPrefs> get() async =>
      NotifyPrefs.fromJson(await _api.get('/v1/notification-prefs'));

  @override
  Future<NotifyPrefs> save(NotifyPrefs prefs, {String? digestEmail}) async =>
      NotifyPrefs.fromJson(
        await _api.put(
          '/v1/notification-prefs',
          body: prefs.toUpdateJson(digestEmail: digestEmail),
        ),
      );

  @override
  Future<NotifyPrefs> verifyEmail(String code) async => NotifyPrefs.fromJson(
        await _api.post(
          '/v1/notification-prefs/verify-email',
          body: <String, dynamic>{'code': code.trim()},
        ),
      );

  @override
  Future<NotifyPrefs> resendCode() async => NotifyPrefs.fromJson(
        await _api.post('/v1/notification-prefs/resend-code'),
      );
}

class MockNotifyPrefsRepository implements NotifyPrefsRepository {
  NotifyPrefs _prefs = const NotifyPrefs(
    channels: {
      'price_drop': {'in_app', 'push'},
      'below_target': {'in_app', 'push', 'email'},
      'cheaper_equivalent': {'in_app'},
      'back_in_stock': {'in_app', 'push'},
      'new_results': {'in_app'},
      'shipment_status': {'in_app', 'push'},
      'shipment_delayed': {'in_app', 'push'},
    },
    quietStart: '22:00',
    quietEnd: '07:00',
    language: 'ar',
  );

  @override
  Future<NotifyPrefs> get() async {
    await mockDelay(150);
    return _prefs;
  }

  /// The fixed code the mock accepts.
  static const String mockCode = '123456';

  String? _pendingFull;

  @override
  Future<NotifyPrefs> save(NotifyPrefs prefs, {String? digestEmail}) async {
    await mockDelay(150);
    var next = prefs.copyWith(
      email: _prefs.email,
      digestEmailVerified: _prefs.digestEmailVerified,
    );
    final d = digestEmail?.trim();
    if (d == null) {
      next = next.copyWith(digestEmailPending: _prefs.digestEmailPending);
    } else if (d.isEmpty) {
      _pendingFull = null;
      next = NotifyPrefs(
        channels: next.channels,
        quietStart: next.quietStart,
        quietEnd: next.quietEnd,
        timezone: next.timezone,
        language: next.language,
      );
    } else {
      _pendingFull = d;
      next = NotifyPrefs(
        channels: next.channels,
        quietStart: next.quietStart,
        quietEnd: next.quietEnd,
        timezone: next.timezone,
        language: next.language,
        digestEmailPending: maskEmail(d),
      );
    }
    _prefs = next;
    return _prefs;
  }

  @override
  Future<NotifyPrefs> verifyEmail(String code) async {
    await mockDelay(150);
    final pending = _pendingFull;
    if (pending == null) {
      throw ApiException(status: 409, code: 'no_pending', message: 'No pending address');
    }
    if (code.trim() != mockCode) {
      throw ApiException(status: 422, code: 'invalid_code', message: 'Invalid code');
    }
    _pendingFull = null;
    _prefs = NotifyPrefs(
      channels: _prefs.channels,
      quietStart: _prefs.quietStart,
      quietEnd: _prefs.quietEnd,
      timezone: _prefs.timezone,
      language: _prefs.language,
      email: pending,
      digestEmailVerified: true,
    );
    return _prefs;
  }

  @override
  Future<NotifyPrefs> resendCode() async {
    await mockDelay(150);
    if (_pendingFull == null) {
      throw ApiException(status: 409, code: 'no_pending', message: 'No pending address');
    }
    return _prefs;
  }
}

final notifyPrefsRepositoryProvider = Provider<NotifyPrefsRepository>((ref) {
  final api = ref.watch(apiClientProvider);
  return api.isMock ? MockNotifyPrefsRepository() : LiveNotifyPrefsRepository(api);
});
