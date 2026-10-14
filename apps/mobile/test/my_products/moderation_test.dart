import 'dart:convert';
import 'dart:io';

import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/features/my_products/my_products_logic.dart';
import 'package:factory_finder/features/my_products/my_products_models.dart';
import 'package:factory_finder/features/my_products/my_products_repository.dart';
import 'package:flutter_test/flutter_test.dart';

dynamic _fixture(String name) =>
    jsonDecode(File('test/fixtures/live/$name.json').readAsStringSync());

void main() {
  group('parsing', () {
    test('moderated fixture exposes status, source, reason and date', () {
      final page = parseOwnedPage(_fixture('my_listings_moderated'));
      expect(page.items, hasLength(2));
      final a = page.items[0];
      expect(a.status, ListingStatus.pendingReview);
      expect(a.isModerated, isTrue);
      expect(a.moderationSource, 'report');
      expect(a.moderationReason, 'Received 3 reports');
      expect(a.moderatedAt, isNotNull);
      final b = page.items[1];
      expect(b.status, ListingStatus.hidden);
      expect(b.moderationSource, 'admin');
      expect(b.moderationReason, 'Prohibited item');
    });

    test('ordinary listings carry no moderation data', () {
      final page = parseOwnedPage(_fixture('my_listings'));
      for (final l in page.items) {
        expect(l.isModerated, isFalse);
        expect(l.moderationReason, isNull);
        expect(l.moderationSource, isNull);
        expect(l.moderatedAt, isNull);
      }
    });

    test('blank reason is treated as absent; copyWith keeps and clears', () {
      final l = OwnedListing.fromJson({
        'id': 'x',
        'status': 'hidden',
        'moderation_reason': '  ',
        'moderation_source': 'auto',
      });
      expect(l.status, ListingStatus.hidden);
      expect(l.moderationReason, isNull);
      final c = l.copyWith(updatedAt: DateTime(2026));
      expect(c.moderationSource, 'auto');
      expect(c.status, ListingStatus.hidden);
      final cleared = l.copyWith(status: ListingStatus.draft, clearModeration: true);
      expect(cleared.moderationSource, isNull);
    });

    test('status filters include the moderation states', () {
      expect(kStatusFilters, containsAll(<ListingStatus>[
        ListingStatus.pendingReview,
        ListingStatus.hidden,
      ]));
      expect(ListingStatus.pendingReview.json, 'pending_review');
    });
  });

  group('mock backend', () {
    OwnedListing draftListing(MockMyListingsBackend b) => b.create(const ProductDraft(
          title: 'Lamp',
          category: 'lighting',
          priceMin: '1',
          priceMax: '2',
        ));

    test('moderated listings cannot be published and keep their reason on edit', () async {
      final backend = MockMyListingsBackend();
      final created = draftListing(backend);
      backend.setStatus(created.id, ListingStatus.published);
      backend.moderate(created.id, ListingStatus.pendingReview, reason: 'Received 3 reports');

      expect(
        () => backend.setStatus(created.id, ListingStatus.published),
        throwsA(isA<ApiException>()
            .having((e) => e.status, 'status', 409)
            .having((e) => e.code, 'code', 'listing_moderated')),
      );
      expect(myProductsErrorKey(ApiException(status: 409, code: 'listing_moderated', message: 'm')),
          'myp.err.moderated');

      final edited = backend.update(
        created.id,
        created.toDraft(),
      );
      expect(edited.status, ListingStatus.pendingReview);
      expect(edited.moderationReason, 'Received 3 reports');
    });

    test('repository filters by moderation status', () async {
      final backend = MockMyListingsBackend();
      final a = draftListing(backend);
      draftListing(backend);
      backend.moderate(a.id, ListingStatus.hidden, source: 'admin', reason: 'Prohibited item');
      final repo = MyListingsRepository(
        ApiClient(baseUrl: 'http://unused.invalid', isMock: true),
        backend,
      );
      final hidden = await repo.list(status: ListingStatus.hidden);
      expect(hidden.items.single.id, a.id);
      expect(hidden.items.single.moderationSource, 'admin');
      expect((await repo.list(status: ListingStatus.pendingReview)).total, 0);
    });
  });
}
