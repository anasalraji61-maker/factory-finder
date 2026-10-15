import 'dart:convert';

import 'package:factory_finder/core/storage/key_value_store.dart';
import 'package:factory_finder/core/storage/read_cache.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  late MemoryStore store;
  late DateTime clock;

  ReadCache make({int maxChars = kReadCacheMaxChars, int maxEntries = 5}) =>
      ReadCache(
        store,
        maxChars: maxChars,
        maxEntries: maxEntries,
        now: () => clock,
      );

  setUp(() {
    store = MemoryStore();
    clock = DateTime(2026, 10, 15, 12);
  });

  test('round-trips a value and reports when it was saved', () async {
    final cache = make();
    await cache.put('slot', 'a', <String, Object?>{'n': 1});
    final hit = await cache.get('slot', 'a');
    expect(hit, isNotNull);
    expect((hit!.data as Map)['n'], 1);
    expect(hit.savedAt, clock);
    expect(await cache.get('slot', 'other'), isNull);
    expect(await cache.get('empty', 'a'), isNull);
  });

  test('entries expire after the 24h TTL', () async {
    final cache = make();
    await cache.put('slot', 'a', 'x');
    clock = clock.add(const Duration(hours: 23, minutes: 59));
    expect(await cache.get('slot', 'a'), isNotNull);
    clock = clock.add(const Duration(minutes: 2));
    expect(await cache.get('slot', 'a'), isNull);
  });

  test('expired entries are dropped when the slot is next written', () async {
    final cache = make();
    await cache.put('slot', 'old', 'x');
    clock = clock.add(const Duration(hours: 30));
    await cache.put('slot', 'new', 'y');
    final stored = jsonDecode(store.data['slot']!) as List;
    expect(stored.length, 1);
    expect((stored.first as Map)['k'], 'new');
  });

  test('keeps only maxEntries, newest first', () async {
    final cache = make(maxEntries: 2);
    await cache.put('slot', 'a', 1);
    await cache.put('slot', 'b', 2);
    await cache.put('slot', 'c', 3);
    expect(await cache.get('slot', 'a'), isNull);
    expect((await cache.get('slot', 'b'))!.data, 2);
    expect((await cache.get('slot', 'c'))!.data, 3);
  });

  test('re-putting a key replaces it instead of duplicating', () async {
    final cache = make();
    await cache.put('slot', 'a', 1);
    await cache.put('slot', 'a', 2);
    expect((jsonDecode(store.data['slot']!) as List).length, 1);
    expect((await cache.get('slot', 'a'))!.data, 2);
  });

  test('size cap evicts oldest entries; an oversized entry is not stored', () async {
    final cache = make(maxChars: 300);
    final blob = 'z' * 120;
    await cache.put('slot', 'a', blob);
    await cache.put('slot', 'b', blob);
    await cache.put('slot', 'c', blob);
    expect(store.data['slot']!.length, lessThanOrEqualTo(300));
    expect(await cache.get('slot', 'a'), isNull);
    expect(await cache.get('slot', 'c'), isNotNull);

    await cache.put('slot', 'huge', 'q' * 1000);
    expect(await cache.get('slot', 'huge'), isNull);
    expect(await cache.get('slot', 'c'), isNotNull);
  });

  test('corrupt or foreign data reads as a miss and never throws', () async {
    store.data['slot'] = '{not json';
    final cache = make();
    expect(await cache.get('slot', 'a'), isNull);
    store.data['slot'] = '{"a":1}';
    expect(await cache.get('slot', 'a'), isNull);
    store.data['slot'] = '[1,"x",{"k":"a"}]';
    expect(await cache.get('slot', 'a'), isNull);
    await cache.put('slot', 'a', 1);
    expect((await cache.get('slot', 'a'))!.data, 1);
  });

  test('a failing store never throws', () async {
    final cache = ReadCache(_BrokenStore(), now: () => clock);
    await cache.put('slot', 'a', 1);
    expect(await cache.get('slot', 'a'), isNull);
    await cache.clear();
  });

  test('clear wipes the known slots only', () async {
    final cache = make();
    await cache.put(kSearchCacheSlot, 'a', 1);
    await cache.put(kHomeFeedCacheSlot, 'a', 1);
    store.data['locale'] = 'ar';
    await cache.clear();
    expect(store.data.keys.toList(), <String>['locale']);
  });

  test('only public catalogue slots exist', () {
    expect(kReadCacheSlots, <String>[kSearchCacheSlot, kHomeFeedCacheSlot]);
    for (final s in kReadCacheSlots) {
      expect(s, startsWith(kReadCachePrefix));
      expect(s, isNot(contains('deal')));
      expect(s, isNot(contains('chat')));
      expect(s, isNot(contains('invoice')));
      expect(s, isNot(contains('verif')));
    }
  });
}

class _BrokenStore implements KeyValueStore {
  @override
  Future<String?> get(String key) => throw StateError('boom');

  @override
  Future<void> set(String key, String value) => throw StateError('boom');

  @override
  Future<void> remove(String key) => throw StateError('boom');
}
