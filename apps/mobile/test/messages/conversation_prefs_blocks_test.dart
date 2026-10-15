import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/i18n/error_messages.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/features/messages/data/message_models.dart';
import 'package:factory_finder/features/messages/data/messages_repository.dart';
import 'package:flutter_test/flutter_test.dart';

class _Call {
  _Call(this.method, this.path, this.query, this.data);
  final String method;
  final String path;
  final Map<String, dynamic> query;
  final Object? data;
}

/// Records requests and answers with canned JSON per path.
class _Adapter implements HttpClientAdapter {
  final List<_Call> calls = [];

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    calls.add(_Call(options.method, options.path, options.queryParameters, options.data));
    Object? body;
    var status = 200;
    if (options.path == '/v1/conversations/unread-total') {
      body = {'unread_total': 4};
    } else if (options.path == '/v1/blocks' && options.method == 'GET') {
      body = {
        'items': [
          {'user_id': 'usr_a', 'blocked_at': '2026-10-14T10:00:00Z'},
          {'blocked_at': '2026-10-14T10:00:00Z'},
        ],
      };
    } else if (options.path.startsWith('/v1/blocks/')) {
      status = 204;
    } else if (options.path.endsWith('/preferences')) {
      body = {'conversation_id': 'conv_1', 'muted': true, 'archived': false};
    } else if (options.path == '/v1/conversations') {
      body = {'items': <Object>[], 'total': 0};
    }
    return ResponseBody.fromString(
      body == null ? '' : jsonEncode(body),
      status,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

LiveMessagingRepository _live(_Adapter adapter) {
  final dio = Dio(BaseOptions(baseUrl: 'http://fake'))..httpClientAdapter = adapter;
  return LiveMessagingRepository(
    ApiClient(baseUrl: 'http://fake', isMock: false, dio: dio),
    () => 'usr_me',
  );
}

void main() {
  final t0 = DateTime(2026, 10, 14, 12);

  group('model JSON', () {
    test('muted/archived parse and round trip, default false', () {
      final c = Conversation.fromJson({
        'id': 'c1',
        'title': 'x',
        'muted': true,
        'archived': true,
        'updated_at': '2026-10-14T10:00:00Z',
      });
      expect(c.muted, isTrue);
      expect(c.archived, isTrue);
      final back = Conversation.fromJson(c.toJson());
      expect(back.muted, isTrue);
      expect(back.archived, isTrue);
      final plain = Conversation.fromJson({'id': 'c2', 'title': 'y'});
      expect(plain.muted, isFalse);
      expect(plain.archived, isFalse);
    });

    test('BlockedUser tolerates entries without a user id', () {
      expect(BlockedUser.tryParse({'blocked_at': 'x'}), isNull);
      expect(BlockedUser.tryParse('nope'), isNull);
      final b = BlockedUser.tryParse({'user_id': 'u1', 'blocked_at': '2026-10-14T10:00:00Z'});
      expect(b?.userId, 'u1');
      expect(b?.blockedAt, isNotNull);
    });
  });

  group('live repository', () {
    test('conversations archived filter is sent only when true', () async {
      final adapter = _Adapter();
      final repo = _live(adapter);
      await repo.conversations();
      await repo.conversations(archived: true);
      expect(adapter.calls[0].query.containsKey('archived'), isFalse);
      expect(adapter.calls[1].query['archived'], true);
    });

    test('preferences body only carries the given fields', () async {
      final adapter = _Adapter();
      final repo = _live(adapter);
      await repo.setPreferences('conv_1', muted: true);
      await repo.setPreferences('conv_1', archived: false);
      expect(adapter.calls[0].method, 'PUT');
      expect(adapter.calls[0].path, '/v1/conversations/conv_1/preferences');
      expect(adapter.calls[0].data, {'muted': true});
      expect(adapter.calls[1].data, {'archived': false});
    });

    test('unread total, blocks list, block and unblock', () async {
      final adapter = _Adapter();
      final repo = _live(adapter);
      expect(await repo.unreadTotal(), 4);
      final blocked = await repo.blockedUsers();
      expect(blocked.map((b) => b.userId), ['usr_a']);
      await repo.blockUser('usr_a');
      await repo.unblockUser('usr_a');
      final last = adapter.calls.sublist(adapter.calls.length - 2);
      expect(last[0].method, 'PUT');
      expect(last[0].path, '/v1/blocks/usr_a');
      expect(last[1].method, 'DELETE');
      expect(last[1].path, '/v1/blocks/usr_a');
    });
  });

  group('mock repository', () {
    test('archive hides from inbox, lists under archived; unread excludes muted/archived',
        () async {
      final repo = MockMessagingRepository(clock: () => t0, autoReply: false);
      expect(await repo.unreadTotal(), 7);
      await repo.setPreferences('cnv_001', muted: true);
      expect(await repo.unreadTotal(), 5);
      await repo.setPreferences('cnv_005', archived: true);
      expect(await repo.unreadTotal(), 2);
      final inbox = await repo.conversations();
      expect(inbox.any((c) => c.id == 'cnv_005'), isFalse);
      expect(inbox.firstWhere((c) => c.id == 'cnv_001').muted, isTrue);
      final archived = await repo.conversations(archived: true);
      expect(archived.map((c) => c.id), ['cnv_005']);
      await repo.setPreferences('cnv_005', archived: false);
      expect((await repo.conversations(archived: true)), isEmpty);
    });

    test('block hides threads and refuses new conversations; unblock restores', () async {
      final repo = MockMessagingRepository(clock: () => t0, autoReply: false);
      await repo.blockUser('sup_001');
      expect((await repo.conversations()).any((c) => c.id == 'cnv_001'), isFalse);
      expect((await repo.blockedUsers()).map((b) => b.userId), ['sup_001']);
      await expectLater(
        repo.createConversation(supplierId: 'sup_001'),
        throwsA(isA<ApiException>().having((e) => e.code, 'code', 'user_blocked')),
      );
      await expectLater(
        repo.setPreferences('cnv_001', muted: true),
        throwsA(isA<ApiException>().having((e) => e.status, 'status', 404)),
      );
      await repo.unblockUser('sup_001');
      expect((await repo.conversations()).any((c) => c.id == 'cnv_001'), isTrue);
      expect(await repo.blockedUsers(), isEmpty);
    });
  });

  test('user_blocked has localized ar + en text', () {
    final err = ApiException(status: 422, code: 'user_blocked', message: 'raw');
    final key = apiErrorKey(err);
    expect(key, 'error.user_blocked');
    final ar = AppStrings.lookup('ar', key!);
    final en = AppStrings.lookup('en', key);
    expect(ar, isNot(key));
    expect(en, isNot(key));
    expect(ar, isNot(en));
  });
}
