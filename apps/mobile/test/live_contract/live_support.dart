import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:factory_finder/core/api/api_client.dart';

/// Live-contract tests talk to a real local stack (scripts/serve_stack.py).
/// They only run when both env vars are set; otherwise they are skipped.
///   FF_LIVE_BASE_URL  gateway URL, e.g. http://localhost:8000
///   FF_LIVE_INFO      path of the JSON written by serve_stack.py
const String kLiveSkipReason =
    'Live contract tests are disabled: set FF_LIVE_BASE_URL and FF_LIVE_INFO '
    '(start the backend with `python scripts/serve_stack.py`, see '
    '.github/workflows/mobile-live.yml).';

String? get liveBaseUrl {
  final v = Platform.environment['FF_LIVE_BASE_URL'];
  return (v == null || v.isEmpty) ? null : v.replaceAll(RegExp(r'/+$'), '');
}

String? get liveInfoPath {
  final v = Platform.environment['FF_LIVE_INFO'];
  return (v == null || v.isEmpty) ? null : v;
}

bool get liveEnabled => liveBaseUrl != null && liveInfoPath != null;

/// Seed data written by serve_stack.py (ids and tokens).
class LiveInfo {
  LiveInfo(this.json);

  factory LiveInfo.load() => LiveInfo(
      Map<String, dynamic>.from(jsonDecode(File(liveInfoPath!).readAsStringSync()) as Map));

  final Map<String, dynamic> json;

  String? str(String key) => json[key] as String?;
  Map<String, dynamic> user(String role) =>
      Map<String, dynamic>.from(json[role] as Map);
  String? get listingId => str('listing_id');
  String? get supplierId => str('external_supplier_id');
  String? get claimedSupplierId => str('claimed_supplier_id');
  String? get nativeListingId =>
      json['native_published'] == true ? str('native_listing_id') : null;
  String? get requestId => str('request_id');
  String? get dealId => str('deal_id');
  String? get conversationId => str('conversation_id');
  String? get shipmentId => str('shipment_id');
  String? get alertId => str('alert_id');
  String? get freightRequestId => str('freight_request_id');
  String get buyerId => user('buyer')['id'] as String;
}

/// Adds an unknown field to every JSON object of every response, so the
/// parsers prove they tolerate fields the app has never heard of.
class ExtraFieldsInterceptor extends Interceptor {
  static dynamic _inject(dynamic v) {
    if (v is Map) {
      final out = <String, dynamic>{
        for (final e in v.entries) e.key.toString(): _inject(e.value),
      };
      out['x_unknown_field'] = 'drift-probe';
      out['x_unknown_object'] = <String, dynamic>{'a': 1, 'b': <dynamic>[]};
      return out;
    }
    if (v is List) return [for (final e in v) _inject(e)];
    return v;
  }

  @override
  void onResponse(Response response, ResponseInterceptorHandler handler) {
    response.data = _inject(response.data);
    handler.next(response);
  }
}

/// A real dio-based [ApiClient] pointed at the live stack, signed in as [role].
ApiClient liveClient(String baseUrl, LiveInfo info, String role,
    {bool extraFields = false}) {
  final dio = Dio(BaseOptions(
    baseUrl: baseUrl,
    connectTimeout: const Duration(seconds: 10),
    receiveTimeout: const Duration(seconds: 30),
  ));
  if (extraFields) dio.interceptors.add(ExtraFieldsInterceptor());
  final tokens = TokenStore();
  final u = info.user(role);
  tokens.set(u['token'] as String, u['refresh_token'] as String?);
  return ApiClient(baseUrl: baseUrl, isMock: false, dio: dio, tokens: tokens);
}

/// Collects every mismatch instead of stopping at the first one.
class ContractReport {
  final List<String> problems = [];
  int checks = 0;

  /// Runs [body]; an exception (parse error, HTTP error, cast error) is a
  /// mismatch. [Ctx.need]/[Ctx.nonEmpty] record soft failures.
  Future<void> check(String mode, String name, Future<void> Function(Ctx c) body) async {
    checks++;
    final ctx = Ctx('[$mode] $name', problems);
    try {
      await body(ctx);
    } on DioException catch (e) {
      problems.add('[$mode] $name: HTTP/Dio ${e.response?.statusCode} ${e.message} ${e.response?.data}');
    } catch (e, st) {
      final first = st.toString().split('\n').take(3).join(' | ');
      problems.add('[$mode] $name: ${e.runtimeType}: $e  @ $first');
    }
  }

  String render() {
    final b = StringBuffer()
      ..writeln('')
      ..writeln('==== LIVE CONTRACT REPORT: $checks checks, ${problems.length} mismatches ====');
    for (final p in problems) {
      b.writeln(' - $p');
    }
    return b.toString();
  }
}

class Ctx {
  Ctx(this.name, this._problems);
  final String name;
  final List<String> _problems;

  /// [value] must be non-null (and, for strings/collections, non-empty).
  void need(Object? value, String field) {
    final bad = value == null ||
        (value is String && value.isEmpty) ||
        (value is Iterable && value.isEmpty) ||
        (value is Map && value.isEmpty);
    if (bad) _problems.add('$name: `$field` is null/empty ($value)');
  }

  /// A seed id the stack failed to create: reported, so it is not silently skipped.
  bool seeded(String? id, String what) {
    if (id == null || id.isEmpty) {
      _problems.add('$name: seed data `$what` missing in FF_LIVE_INFO (see seed_errors)');
      return false;
    }
    return true;
  }
}
