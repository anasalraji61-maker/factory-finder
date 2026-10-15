import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/i18n/error_messages.dart';
import 'package:factory_finder/core/i18n/tr.dart';
import 'package:factory_finder/features/messages/data/chat_logic.dart';
import 'package:factory_finder/features/messages/data/message_models.dart';
import 'package:factory_finder/features/messages/data/messages_repository.dart';
import 'package:factory_finder/features/reviews/reviews_models.dart';
import 'package:factory_finder/features/reviews/reviews_repository.dart';
import 'package:flutter_test/flutter_test.dart';

/// Reviews repository whose delete always fails with [error].
class _FailingReviews implements ReviewsRepository {
  _FailingReviews(this.error);

  final Object error;

  @override
  Future<void> delete(String reviewId) async => throw error;

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

/// Messaging repository whose send always fails with [error].
class _FailingChat implements MessagingRepository {
  _FailingChat(this.error);

  final Object error;

  @override
  Future<ChatMessage> send(
    String conversationId,
    String text, {
    List<MessageAttachment> attachments = const <MessageAttachment>[],
    String? clientId,
  }) async =>
      throw error;

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

ApiException _api(String code, [int status = 409]) =>
    ApiException(status: status, code: code, message: 'raw');

void main() {
  const shared = <String>[
    'rating_too_early',
    'rating_pair_limit',
    'conversation_limit_reached',
    'conversation_full',
    'file_in_use',
    'upstream_timeout',
  ];

  test('reviews: failures from the repository map to shared ar+en text', () async {
    for (final code in shared) {
      final repo = _FailingReviews(_api(code));
      Object? caught;
      try {
        await repo.delete('rev_1');
      } catch (e) {
        caught = e;
      }
      expect(caught, isNotNull, reason: code);
      final key = reviewErrorKey(caught!);
      expect(key, 'error.$code', reason: code);
      expect(AppStrings.lookup('ar', key), isNot(key), reason: code);
      expect(AppStrings.lookup('en', key), isNot(key), reason: code);
    }
  });

  test('chat: failures from the repository map to shared ar+en text', () async {
    for (final code in shared) {
      final repo = _FailingChat(_api(code));
      Object? caught;
      try {
        await repo.send('c1', 'hi');
      } catch (e) {
        caught = e;
      }
      expect(caught, isNotNull, reason: code);
      final key = sendErrorKey(caught!);
      expect(key, 'error.$code', reason: code);
      expect(AppStrings.lookup('ar', key!), isNot(key), reason: code);
      expect(AppStrings.lookup('en', key), isNot(key), reason: code);
    }
  });

  test('existing mappings are unchanged', () {
    expect(reviewErrorKey(_api('review_already_exists')), 'reviews.err.review_already_exists');
    expect(reviewErrorKey(_api('timeout', 0)), 'reviews.err.network');
    expect(reviewErrorKey(StateError('x')), 'reviews.err.generic');
    expect(sendErrorKey(_api('too_many_attachments', 422)), 'messages.err.too_many');
    expect(sendErrorKey(_api('validation_error', 422)), isNull);
    expect(sendErrorKey(StateError('x')), isNull);
  });

  test('every shared code is in the central map', () {
    for (final code in shared) {
      expect(kApiErrorKeys.containsKey(code), isTrue, reason: code);
    }
  });
}
