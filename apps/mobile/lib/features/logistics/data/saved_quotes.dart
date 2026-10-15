import 'dart:convert';

import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/core/storage/key_value_store.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

const String kSavedQuotesKey = 'logistics.saved_quotes.v1';
const int kMaxSavedQuotes = 10;

/// A landed-cost quote the user chose to keep. Prices age: the screens show
/// [savedAt] and a "prices may have changed" note.
class SavedQuote {
  const SavedQuote({required this.quote, required this.savedAt, this.incoterm});

  final LandedCostQuote quote;
  final DateTime savedAt;
  final Incoterm? incoterm;

  Map<String, dynamic> toJson() => {
        'saved_at': savedAt.toUtc().toIso8601String(),
        'quote': quote.toJson(),
        if (incoterm != null) 'incoterm': incoterm!.json,
      };

  static SavedQuote? tryParse(Object? v) {
    if (v is! Map) return null;
    try {
      final j = Map<String, dynamic>.from(v);
      final q = j['quote'];
      if (q is! Map) return null;
      return SavedQuote(
        quote: LandedCostQuote.fromJson(Map<String, dynamic>.from(q)),
        savedAt: DateTime.tryParse('${j['saved_at']}') ?? DateTime.now().toUtc(),
        incoterm: j['incoterm'] == null ? null : incotermFromJson('${j['incoterm']}'),
      );
    } catch (_) {
      return null;
    }
  }
}

/// Persists up to [kMaxSavedQuotes] quotes (newest first) in the key-value
/// store. Corrupt or unavailable storage never breaks the screens.
class SavedQuotesNotifier extends StateNotifier<List<SavedQuote>> {
  SavedQuotesNotifier(this._store) : super(const []) {
    _ready = _load();
  }

  final KeyValueStore _store;
  late final Future<void> _ready;

  Future<void> get ready => _ready;

  Future<void> _load() async {
    try {
      final raw = await _store.get(kSavedQuotesKey);
      if (raw == null || raw.isEmpty) return;
      final list = jsonDecode(raw);
      if (list is! List) return;
      final loaded = <SavedQuote>[
        for (final e in list)
          if (SavedQuote.tryParse(e) != null) SavedQuote.tryParse(e)!,
      ];
      // Anything saved while loading is already in state and stays first.
      if (!mounted) return;
      final ids = state.map((s) => s.quote.id).toSet();
      state = [
        ...state,
        ...loaded.where((s) => !ids.contains(s.quote.id)),
      ].take(kMaxSavedQuotes).toList();
    } catch (_) {
      // ignore: unreadable storage
    }
  }

  Future<void> _persist() async {
    try {
      await _store.set(
        kSavedQuotesKey,
        jsonEncode(state.map((s) => s.toJson()).toList()),
      );
    } catch (_) {
      // best effort
    }
  }

  /// Saves (or refreshes) [quote]; the same quote id is never duplicated.
  Future<void> save(LandedCostQuote quote, {Incoterm? incoterm, DateTime? now}) async {
    await _ready;
    if (!mounted) return;
    final entry = SavedQuote(
      quote: quote,
      savedAt: (now ?? DateTime.now()).toUtc(),
      incoterm: incoterm,
    );
    state = [
      entry,
      ...state.where((s) => s.quote.id != quote.id),
    ].take(kMaxSavedQuotes).toList();
    await _persist();
  }

  Future<void> remove(String quoteId) async {
    await _ready;
    if (!mounted) return;
    state = state.where((s) => s.quote.id != quoteId).toList();
    await _persist();
  }

  bool contains(String quoteId) => state.any((s) => s.quote.id == quoteId);
}

final savedQuotesProvider =
    StateNotifierProvider<SavedQuotesNotifier, List<SavedQuote>>(
  (ref) => SavedQuotesNotifier(ref.watch(keyValueStoreProvider)),
);
