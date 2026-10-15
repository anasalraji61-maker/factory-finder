import 'dart:convert';

import 'package:factory_finder/core/storage/key_value_store.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Storage key of the on-device recently viewed listing ids (JSON list).
const String kRecentlyViewedKey = 'recently_viewed_ids';

/// Matches the server limit of `ref` on GET /v1/recommendations.
const int kRecentlyViewedCap = 20;

/// Puts [id] first (most recent first), removes older copies, keeps [cap].
List<String> pushRecent(List<String> current, String id, {int cap = kRecentlyViewedCap}) {
  final trimmed = id.trim();
  if (trimmed.isEmpty) return List<String>.of(current);
  return [
    trimmed,
    for (final c in current)
      if (c != trimmed) c,
  ].take(cap).toList();
}

String encodeRecent(List<String> ids) => jsonEncode(ids);

/// Tolerant decoder: bad JSON or non-string items give an empty/filtered list.
List<String> decodeRecent(String? raw, {int cap = kRecentlyViewedCap}) {
  if (raw == null || raw.isEmpty) return const [];
  try {
    final data = jsonDecode(raw);
    if (data is! List) return const [];
    final seen = <String>{};
    final out = <String>[];
    for (final e in data) {
      if (e is String && e.trim().isNotEmpty && seen.add(e.trim())) {
        out.add(e.trim());
      }
    }
    return out.take(cap).toList();
  } catch (_) {
    return const [];
  }
}

class RecentlyViewedState {
  const RecentlyViewedState({this.ids = const [], this.loaded = false});

  final List<String> ids;

  /// False until the stored list has been read (or replaced by a clear).
  final bool loaded;
}

/// Local-only history: never sent anywhere except as the stateless `ref`
/// parameter of the recommendations request.
class RecentlyViewedNotifier extends StateNotifier<RecentlyViewedState> {
  RecentlyViewedNotifier(this._store) : super(const RecentlyViewedState()) {
    ready = _load();
  }

  final KeyValueStore _store;

  /// Completes once the stored ids have been read.
  late final Future<void> ready;

  Future<void> _load() async {
    var stored = const <String>[];
    try {
      stored = decodeRecent(await _store.get(kRecentlyViewedKey));
    } catch (_) {
      stored = const [];
    }
    if (!mounted || state.loaded) return; // disposed, or cleared meanwhile
    state = RecentlyViewedState(ids: stored, loaded: true);
  }

  Future<void> add(String id) async {
    await ready; // never overwrite the stored list before it was read
    if (!mounted) return;
    final current = state.ids;
    final next = pushRecent(current, id);
    if (next.length == current.length) {
      var same = true;
      for (var i = 0; i < next.length; i++) {
        if (next[i] != current[i]) {
          same = false;
          break;
        }
      }
      if (same) return; // already the most recent one
    }
    state = RecentlyViewedState(ids: next, loaded: true);
    await _persist(next);
  }

  Future<void> clear() async {
    state = const RecentlyViewedState(ids: [], loaded: true);
    try {
      await _store.remove(kRecentlyViewedKey);
    } catch (_) {
      // Best effort: the in-memory list is already empty.
    }
  }

  Future<void> _persist(List<String> ids) async {
    try {
      await _store.set(kRecentlyViewedKey, encodeRecent(ids));
    } catch (_) {
      // Storage unavailable: history simply stays in memory.
    }
  }
}

final recentlyViewedProvider =
    StateNotifierProvider<RecentlyViewedNotifier, RecentlyViewedState>(
  (ref) => RecentlyViewedNotifier(ref.watch(keyValueStoreProvider)),
);
