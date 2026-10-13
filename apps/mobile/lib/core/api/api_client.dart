import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

const bool kMockMode = bool.fromEnvironment('FF_MOCK', defaultValue: true);
const String kDefaultBaseUrl = String.fromEnvironment(
  'FF_API_BASE_URL',
  defaultValue: 'http://10.0.2.2:8000',
);

/// Gateway URL used when not in mock mode. Editable from Profile (memory only).
final serverUrlProvider = StateProvider<String>((ref) => kDefaultBaseUrl);

/// Access/refresh tokens, held in memory only.
final tokenStoreProvider = Provider<TokenStore>((ref) => TokenStore());

final apiClientProvider = Provider<ApiClient>(
  (ref) => ApiClient(
    baseUrl: ref.watch(serverUrlProvider),
    isMock: kMockMode,
    tokens: ref.watch(tokenStoreProvider),
  ),
);

/// In-memory token holder shared by every [ApiClient] instance.
class TokenStore {
  String? accessToken;
  String? refreshToken;

  /// Called when the session is dropped (logout or failed refresh).
  void Function()? onCleared;

  bool get hasSession => accessToken != null;

  void set(String access, String? refresh) {
    accessToken = access;
    refreshToken = refresh ?? refreshToken;
  }

  void clear() {
    final had = accessToken != null || refreshToken != null;
    accessToken = null;
    refreshToken = null;
    if (had) onCleared?.call();
  }
}

class ApiClient {
  ApiClient({
    required this.baseUrl,
    required this.isMock,
    TokenStore? tokens,
    Dio? dio,
  })  : tokens = tokens ?? TokenStore(),
        _dio = dio ??
            Dio(
              BaseOptions(
                baseUrl: baseUrl,
                connectTimeout: const Duration(seconds: 10),
                receiveTimeout: const Duration(seconds: 20),
              ),
            );

  /// FF_API_BASE_URL (default http://10.0.2.2:8000), FF_MOCK (default true).
  factory ApiClient.fromEnvironment() =>
      ApiClient(baseUrl: kDefaultBaseUrl, isMock: kMockMode);

  final String baseUrl;
  final bool isMock;
  final TokenStore tokens;
  final Dio _dio;

  Future<bool>? _refreshing;

  Future<dynamic> get(String path, {Map<String, dynamic>? query, bool auth = true}) =>
      _request('GET', path, query: query, auth: auth);

  Future<dynamic> post(String path, {Object? body, bool auth = true}) =>
      _request('POST', path, body: body, auth: auth);

  Future<dynamic> patch(String path, {Object? body}) =>
      _request('PATCH', path, body: body);

  Future<dynamic> delete(String path) => _request('DELETE', path);

  Future<dynamic> _request(
    String method,
    String path, {
    Map<String, dynamic>? query,
    Object? body,
    bool auth = true,
    bool retried = false,
  }) async {
    try {
      final token = tokens.accessToken;
      final response = await _dio.request<dynamic>(
        path,
        data: body,
        queryParameters: query,
        options: Options(
          method: method,
          headers: <String, dynamic>{
            if (auth && token != null) 'Authorization': 'Bearer $token',
          },
        ),
      );
      return response.data;
    } on DioException catch (e) {
      if (e.response?.statusCode == 401 &&
          auth &&
          !retried &&
          tokens.refreshToken != null) {
        final ok = await _refreshOnce();
        if (ok) {
          return _request(method, path,
              query: query, body: body, auth: auth, retried: true);
        }
      }
      throw mapDioError(e);
    }
  }

  Future<bool> _refreshOnce() {
    return _refreshing ??= _doRefresh().whenComplete(() => _refreshing = null);
  }

  Future<bool> _doRefresh() async {
    final refresh = tokens.refreshToken;
    if (refresh == null) return false;
    try {
      final response = await _dio.request<dynamic>(
        '/v1/auth/refresh',
        data: <String, dynamic>{'refresh_token': refresh},
        options: Options(method: 'POST'),
      );
      final data = response.data;
      if (data is Map && data['access_token'] is String) {
        tokens.set(
          data['access_token'] as String,
          data['refresh_token'] as String?,
        );
        return true;
      }
    } on DioException {
      // fall through: session is dropped below
    }
    tokens.clear();
    return false;
  }
}

/// Converts a Dio failure into an [ApiException] using the contract error body
/// `{"error": {"code", "message"}}` (also tolerates FastAPI `detail`).
ApiException mapDioError(DioException e) {
  final status = e.response?.statusCode;
  var code = 'network_error';
  var message = e.message ?? 'Network error';
  if (e.type == DioExceptionType.connectionTimeout ||
      e.type == DioExceptionType.sendTimeout ||
      e.type == DioExceptionType.receiveTimeout) {
    code = 'timeout';
  } else if (status != null) {
    code = 'http_$status';
  }
  final data = e.response?.data;
  if (data is Map) {
    final err = data['error'];
    if (err is Map) {
      code = err['code']?.toString() ?? code;
      message = err['message']?.toString() ?? message;
    } else if (data['detail'] != null) {
      final d = data['detail'];
      message = d is String ? d : d.toString();
    }
  }
  return ApiException(status: status, code: code, message: message);
}

class ApiException implements Exception {
  ApiException({this.status, required this.code, required this.message});

  final int? status;
  final String code;
  final String message;

  bool get isUnauthorized => status == 401;

  @override
  String toString() => 'ApiException($status, $code): $message';
}

/// Short message suitable for a snackbar / error state.
String describeError(Object e) => e is ApiException ? e.message : e.toString();

/// Simulated latency for mock repositories.
Future<void> mockDelay([int milliseconds = 350]) =>
    Future<void>.delayed(Duration(milliseconds: milliseconds));
