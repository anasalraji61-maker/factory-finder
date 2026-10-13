import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

final apiClientProvider = Provider<ApiClient>((ref) => ApiClient.fromEnvironment());

class ApiClient {
  ApiClient({required this.baseUrl, required this.isMock});

  /// FF_API_BASE_URL (default http://10.0.2.2:8000), FF_MOCK (default true).
  factory ApiClient.fromEnvironment() => ApiClient(
        baseUrl: const String.fromEnvironment(
          'FF_API_BASE_URL',
          defaultValue: 'http://10.0.2.2:8000',
        ),
        isMock: const bool.fromEnvironment('FF_MOCK', defaultValue: true),
      );

  final String baseUrl;
  final bool isMock;

  late final Dio _dio = Dio(
    BaseOptions(
      baseUrl: baseUrl,
      connectTimeout: const Duration(seconds: 10),
      receiveTimeout: const Duration(seconds: 20),
    ),
  );

  Future<dynamic> get(String path, {Map<String, dynamic>? query}) =>
      _send(() => _dio.get<dynamic>(path, queryParameters: query));

  Future<dynamic> post(String path, {Object? body}) =>
      _send(() => _dio.post<dynamic>(path, data: body));

  Future<dynamic> patch(String path, {Object? body}) =>
      _send(() => _dio.patch<dynamic>(path, data: body));

  Future<dynamic> delete(String path) =>
      _send(() => _dio.delete<dynamic>(path));

  Future<dynamic> _send(Future<Response<dynamic>> Function() call) async {
    try {
      final response = await call();
      return response.data;
    } on DioException catch (e) {
      var code = 'network_error';
      var message = e.message ?? 'Network error';
      final data = e.response?.data;
      if (data is Map && data['error'] is Map) {
        final err = data['error'] as Map;
        code = err['code']?.toString() ?? code;
        message = err['message']?.toString() ?? message;
      }
      throw ApiException(
        status: e.response?.statusCode,
        code: code,
        message: message,
      );
    }
  }
}

class ApiException implements Exception {
  ApiException({this.status, required this.code, required this.message});

  final int? status;
  final String code;
  final String message;

  @override
  String toString() => 'ApiException($status, $code): $message';
}

/// Simulated latency for mock repositories.
Future<void> mockDelay([int milliseconds = 350]) =>
    Future<void>.delayed(Duration(milliseconds: milliseconds));
