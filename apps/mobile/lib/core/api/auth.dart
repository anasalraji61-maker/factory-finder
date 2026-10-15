import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/storage/key_value_store.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Signed-in user (gateway `Me`). Only the fields the app needs.
class Me {
  const Me({
    required this.id,
    required this.name,
    this.email,
    this.phone,
    this.company,
    this.role = 'buyer',
    this.displayCurrency,
    this.language,
    this.defaultDestination,
    this.supplierId,
    String? supplierClaimStatus,
  }) : supplierClaimStatus = supplierClaimStatus ??
            (supplierId == null ? 'none' : 'verified');

  final String id;
  final String name;
  final String? email;
  final String? phone;
  final String? company;
  final String role;
  final String? displayCurrency;
  final String? language;
  final Location? defaultDestination;

  /// Catalog supplier claimed by this user (`sup_...`), or null.
  final String? supplierId;

  /// none | pending | verified. Pending claims are under admin review.
  /// Defaults to verified when only a supplier id is present (older servers).
  final String supplierClaimStatus;

  /// Copy with [supplierId] replaced (null releases the claim). A new claim
  /// starts as pending unless [status] says otherwise.
  Me withSupplierId(String? value, {String? status}) => Me(
        id: id,
        name: name,
        email: email,
        phone: phone,
        company: company,
        role: role,
        displayCurrency: displayCurrency,
        language: language,
        defaultDestination: defaultDestination,
        supplierId: value,
        supplierClaimStatus: value == null ? 'none' : (status ?? 'pending'),
      );

  factory Me.fromJson(Map<String, dynamic> j) {
    final dest = j['default_destination'];
    return Me(
      id: (j['id'] ?? '').toString(),
      name: (j['name'] ?? '').toString(),
      email: j['email'] as String?,
      phone: j['phone'] as String?,
      company: j['company'] as String?,
      role: (j['role'] as String?) ?? 'buyer',
      displayCurrency: j['display_currency'] as String?,
      language: j['language'] as String?,
      defaultDestination: dest is Map
          ? Location.fromJson(Map<String, dynamic>.from(dest))
          : null,
      supplierId: j['supplier_id'] is String &&
              (j['supplier_id'] as String).isNotEmpty
          ? j['supplier_id'] as String
          : null,
      supplierClaimStatus: const {'none', 'pending', 'verified'}
              .contains(j['supplier_claim_status'])
          ? j['supplier_claim_status'] as String
          : null,
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        if (email != null) 'email': email,
        if (phone != null) 'phone': phone,
        if (company != null) 'company': company,
        'role': role,
        if (displayCurrency != null) 'display_currency': displayCurrency,
        if (language != null) 'language': language,
        if (defaultDestination != null)
          'default_destination': defaultDestination!.toJson(),
        if (supplierId != null) 'supplier_id': supplierId,
        'supplier_claim_status': supplierClaimStatus,
      };
}

class AuthRepository {
  AuthRepository(this._api);

  final ApiClient _api;

  Future<Me> login({String? email, String? phone, required String password}) async {
    if (_api.isMock) {
      await mockDelay(300);
      return _mockSession(email: email, phone: phone, name: null);
    }
    final json = await _api.post(
      '/v1/auth/login',
      auth: false,
      body: <String, dynamic>{
        if (email != null && email.isNotEmpty) 'email': email,
        if (phone != null && phone.isNotEmpty) 'phone': phone,
        'password': password,
      },
    );
    return _finish(json);
  }

  Future<Me> register({
    String? email,
    String? phone,
    required String password,
    required String name,
  }) async {
    if (_api.isMock) {
      await mockDelay(300);
      return _mockSession(email: email, phone: phone, name: name);
    }
    final json = await _api.post(
      '/v1/auth/register',
      auth: false,
      body: <String, dynamic>{
        if (email != null && email.isNotEmpty) 'email': email,
        if (phone != null && phone.isNotEmpty) 'phone': phone,
        'password': password,
        'name': name,
      },
    );
    return _finish(json);
  }

  void logout() => _api.tokens.clear();

  /// Revokes every session of the user on the server (any 2xx is success).
  /// A 401 means this session is already gone, which is the goal: success.
  Future<void> logoutAll() async {
    if (_api.isMock) {
      await mockDelay(200);
      return;
    }
    try {
      await _api.post('/v1/auth/logout-all');
    } on ApiException catch (e) {
      if (!e.isUnauthorized) rethrow;
    }
  }

  /// Restores a session from the stored refresh token: refresh, then
  /// `/v1/me`. Returns null when the session cannot be restored.
  Future<Me?> restoreSession() async {
    if (_api.tokens.refreshToken == null) return null;
    if (_api.isMock) {
      await mockDelay(50);
      _api.tokens.set('mock-access-token', null);
      return Me(id: kMockUserId, name: 'user');
    }
    if (!await _api.refreshSession()) {
      // Tokens still present => the refresh failed for a transient reason
      // (offline / 5xx), not because the session was rejected.
      if (_api.tokens.refreshToken != null) {
        throw ApiException(
          code: 'network_error',
          message: 'Could not reach the server',
        );
      }
      return null;
    }
    final me = await _api.get('/v1/me');
    return Me.fromJson(Map<String, dynamic>.from(me as Map));
  }

  /// Claims (or, with null, releases) a catalog supplier for [current].
  /// Throws [ApiException] code `supplier_claimed` (409) when already taken.
  Future<Me> claimSupplier(Me current, String? supplierId) async {
    if (_api.isMock) {
      await mockDelay(300);
      if (supplierId == kMockTakenSupplierId) {
        throw ApiException(
          status: 409,
          code: 'supplier_claimed',
          message: 'Supplier already claimed',
        );
      }
      return current.withSupplierId(supplierId);
    }
    final json = await _api.patch(
      '/v1/me',
      body: <String, dynamic>{'supplier_id': supplierId},
    );
    return Me.fromJson(Map<String, dynamic>.from(json as Map));
  }

  Future<Me> _finish(dynamic json) async {
    final m = Map<String, dynamic>.from(json as Map);
    _api.tokens.set(
      (m['access_token'] ?? '').toString(),
      m['refresh_token'] as String?,
    );
    final user = m['user'];
    if (user is Map) return Me.fromJson(Map<String, dynamic>.from(user));
    final me = await _api.get('/v1/me');
    return Me.fromJson(Map<String, dynamic>.from(me as Map));
  }

  Me _mockSession({String? email, String? phone, String? name}) {
    _api.tokens.set('mock-access-token', 'mock-refresh-token');
    final handle = (email != null && email.contains('@'))
        ? email.split('@').first
        : (phone ?? 'user');
    return Me(
      id: kMockUserId,
      name: (name != null && name.isNotEmpty) ? name : handle,
      email: email,
      phone: phone,
    );
  }
}

/// Mock mode: claiming this supplier id always fails with 409 supplier_claimed.
const String kMockTakenSupplierId = 'sup_taken';

/// Id of the signed-in user in mock mode (owner of "my requests" fixtures).
const String kMockUserId = 'usr_mock';

final authRepositoryProvider = Provider<AuthRepository>(
  (ref) => AuthRepository(ref.watch(apiClientProvider)),
);

/// Current user, or null when signed out.
class AuthController extends StateNotifier<Me?> {
  AuthController(this._ref) : super(null) {
    _ref.read(tokenStoreProvider).onCleared = () {
      if (mounted) state = null;
    };
    addListener((me) {
      if (me?.id == _lastUserId) return;
      _lastUserId = me?.id;
      // Deferred: the state may change while a widget tree is building.
      Future<void>.microtask(() {
        if (!mounted) return;
        try {
          _ref.read(authEpochProvider.notifier).state++;
        } catch (_) {
          // Provider scope already disposed.
        }
      });
    }, fireImmediately: false);
  }

  String? _lastUserId;

  final Ref _ref;

  AuthRepository get _repo => _ref.read(authRepositoryProvider);

  Future<void> login({String? email, String? phone, required String password}) async {
    state = await _repo.login(email: email, phone: phone, password: password);
  }

  Future<void> register({
    String? email,
    String? phone,
    required String password,
    required String name,
  }) async {
    state = await _repo.register(
      email: email,
      phone: phone,
      password: password,
      name: name,
    );
  }

  Future<void> claimSupplier(String? supplierId) async {
    final current = state;
    if (current == null) return;
    state = await _repo.claimSupplier(current, supplierId);
  }

  /// Loads the stored refresh token and restores the session. Any failure
  /// clears the tokens and leaves the user signed out. Never throws.
  Future<void> restore() async {
    try {
      final tokens = _ref.read(tokenStoreProvider);
      if (tokens.refreshToken == null) {
        final store = _ref.read(secureStoreProvider);
        String? saved;
        try {
          saved = await store.get(kRefreshTokenKey);
        } catch (_) {
          // Unreadable (e.g. corrupt Android Keystore entry): wipe it once so
          // it does not throw on every launch, and start signed out.
          try {
            await store.remove(kRefreshTokenKey);
          } catch (_) {}
          return;
        }
        if (saved == null || saved.isEmpty) return;
        tokens.refreshToken = saved;
      }
      final me = await _repo.restoreSession();
      if (!mounted) return;
      if (me == null) {
        tokens.clear();
        state = null;
      } else {
        state = me;
      }
    } catch (e) {
      if (!mounted) return;
      // Transient failure (offline / server error): stay signed out for this
      // launch but keep the stored refresh token for the next one.
      final transient =
          e is ApiException && (e.status == null || e.status! >= 500);
      if (!transient) _ref.read(tokenStoreProvider).clear();
      state = null;
    }
  }

  void logout() {
    _repo.logout();
    state = null;
  }

  /// Signs out of every device, then locally. Throws (staying signed in) when
  /// the server call fails for a reason other than an already-dead session.
  Future<void> logoutAll() async {
    await _repo.logoutAll();
    logout();
  }
}

final authProvider = StateNotifierProvider<AuthController, Me?>(
  (ref) => AuthController(ref),
);
