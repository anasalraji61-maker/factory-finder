import 'dart:convert';

import 'package:factory_finder/core/storage/key_value_store.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Storage key prefix for every read-cache slot. Only PUBLIC catalogue data
/// may be cached (search results, home feed). Never auth, deals, chats,
/// invoices or verification data.
const String kReadCachePrefix = 'readcache.';

/// Slot holding the most recent successful search result pages.
const String kSearchCacheSlot = '${kReadCachePrefix}search';

/// Slot holding the last home feed page.
const String kHomeFeedCacheSlot = '${kReadCachePrefix}home_feed';

/// Slots wiped on account deletion / sign-out of local state.
const List<String> kReadCacheSlots = <String>[kSearchCacheSlot, kHomeFeedCacheSlot];

const Duration kReadCacheTtl = Duration(hours: 24);

/// Hard cap on the encoded size of one slot (UTF-16 code units of the JSON).
const int kReadCacheMaxChars = 200000;

/// A value read back from the cache.
class CacheHit {
  const CacheHit(this.data, this.savedAt);

  final Object? data;
  final DateTime savedAt;
}

/// Tiny offline read cache on top of [KeyValueStore].
///
/// Each slot stores up to [maxEntries] keyed entries (most recent first).
/// Entries older than [ttl] are ignored and dropped; a slot never exceeds
/// [maxChars] of encoded JSON (oldest entries are evicted first, and a single
/// oversized entry is not stored at all). Every failure is swallowed: the
/// cache is a convenience and must never break a request.
class ReadCache {
  ReadCache(
    this._store, {
    this.ttl = kReadCacheTtl,
    this.maxChars = kReadCacheMaxChars,
    this.maxEntries = 5,
    DateTime Function()? now,
  }) : _now = now ?? DateTime.now;

  final KeyValueStore _store;
  final Duration ttl;
  final int maxChars;
  final int maxEntries;
  final DateTime Function() _now;

  /// Saves [data] (must be JSON-encodable) under [key] in [slot].
  Future<void> put(String slot, String key, Object? data) async {
    try {
      final now = _now();
      final fresh = await _load(slot, now);
      final entries = <Map<String, Object?>>[
        <String, Object?>{
          'k': key,
          't': now.millisecondsSinceEpoch,
          'd': data,
        },
        ...fresh.where((e) => e['k'] != key),
      ];
      while (entries.length > maxEntries) {
        entries.removeLast();
      }
      var encoded = jsonEncode(entries);
      while (encoded.length > maxChars && entries.length > 1) {
        entries.removeLast();
        encoded = jsonEncode(entries);
      }
      if (encoded.length > maxChars) return; // single entry too large
      await _store.set(slot, encoded);
    } catch (_) {
      // best effort
    }
  }

  /// The entry for [key] in [slot], or null when absent, expired or corrupt.
  Future<CacheHit?> get(String slot, String key) async {
    try {
      final now = _now();
      for (final e in await _load(slot, now)) {
        if (e['k'] == key) {
          return CacheHit(
            e['d'],
            DateTime.fromMillisecondsSinceEpoch(e['t'] as int),
          );
        }
      }
    } catch (_) {
      // best effort
    }
    return null;
  }

  Future<void> clear() async {
    for (final s in kReadCacheSlots) {
      try {
        await _store.remove(s);
      } catch (_) {
        // best effort
      }
    }
  }

  /// Valid (unexpired, well-formed) entries of [slot].
  Future<List<Map<String, Object?>>> _load(String slot, DateTime now) async {
    final raw = await _store.get(slot);
    if (raw == null || raw.isEmpty) return <Map<String, Object?>>[];
    final out = <Map<String, Object?>>[];
    try {
      final decoded = jsonDecode(raw);
      if (decoded is! List) return out;
      for (final e in decoded) {
        if (e is! Map) continue;
        final t = e['t'];
        final k = e['k'];
        if (t is! int || k is! String) continue;
        final age = now.difference(DateTime.fromMillisecondsSinceEpoch(t));
        if (age > ttl || age.isNegative) continue;
        out.add(<String, Object?>{'k': k, 't': t, 'd': e['d']});
      }
    } catch (_) {
      return <Map<String, Object?>>[];
    }
    return out;
  }
}

/// Read cache on the settings store (shared_preferences in the app, memory
/// in tests).
final readCacheProvider = Provider<ReadCache>(
  (ref) => ReadCache(ref.watch(keyValueStoreProvider)),
);
