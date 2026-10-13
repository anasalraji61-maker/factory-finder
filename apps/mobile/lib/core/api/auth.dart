import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/models/models.dart';
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
  }

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

  void logout() {
    _repo.logout();
    state = null;
  }
}

final authProvider = StateNotifierProvider<AuthController, Me?>(
  (ref) => AuthController(ref),
);
