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
  });

  final String id;
  final String name;
  final String? email;
  final String? phone;
  final String? company;
  final String role;
  final String? displayCurrency;
  final String? language;
  final Location? defaultDestination;

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

  void logout() {
    _repo.logout();
    state = null;
  }
}

final authProvider = StateNotifierProvider<AuthController, Me?>(
  (ref) => AuthController(ref),
);
