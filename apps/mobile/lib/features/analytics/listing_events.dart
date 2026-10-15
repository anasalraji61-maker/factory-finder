import 'dart:async';

import 'package:factory_finder/core/api/api_client.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Events accepted by POST /v1/listings/{id}/events.
enum ListingEventType {
  view('view'),
  contactClick('contact_click'),
  share('share');

  const ListingEventType(this.json);
  final String json;
}

/// One event the reporter would have sent (kept in [ListingEventReporter.mockEvents]
/// in mock mode so tests can assert on it).
class ListingEventRecord {
  const ListingEventRecord(this.listingId, this.type);

  final String listingId;
  final ListingEventType type;

  @override
  bool operator ==(Object other) =>
      other is ListingEventRecord &&
      other.listingId == listingId &&
      other.type == type;

  @override
  int get hashCode => Object.hash(listingId, type);

  @override
  String toString() => '$listingId:${type.json}';
}

/// Fire-and-forget reporter of anonymous listing events.
///
/// [report] returns immediately and never throws: the UI is never blocked and
/// every failure is swallowed. Each (listing, type) pair is sent at most once
/// per reporter instance (= app session); a failed send that may succeed
/// later (offline, timeout, 5xx) frees the pair again, a 4xx (including 429)
/// does not. Mock mode sends nothing and only records into [mockEvents].
class ListingEventReporter {
  ListingEventReporter(this._api);

  final ApiClient _api;
  final Set<ListingEventRecord> _seen = <ListingEventRecord>{};
  final List<ListingEventRecord> _mockEvents = <ListingEventRecord>[];

  /// Events recorded in mock mode (unmodifiable view).
  List<ListingEventRecord> get mockEvents =>
      List<ListingEventRecord>.unmodifiable(_mockEvents);

  /// True when [report] for this pair would be ignored as a duplicate.
  bool hasReported(String listingId, ListingEventType type) =>
      _seen.contains(ListingEventRecord(listingId, type));

  void report(String listingId, ListingEventType type) {
    if (listingId.isEmpty) return;
    final rec = ListingEventRecord(listingId, type);
    if (!_seen.add(rec)) return;
    if (_api.isMock) {
      _mockEvents.add(rec);
      return;
    }
    unawaited(_send(rec));
  }

  Future<void> _send(ListingEventRecord rec) async {
    try {
      await _api.post(
        '/v1/listings/${Uri.encodeComponent(rec.listingId)}/events',
        body: <String, dynamic>{'type': rec.type.json},
      );
    } catch (e) {
      final status = e is ApiException ? e.status : null;
      if (status == null || status >= 500) _seen.remove(rec);
    }
  }
}

final listingEventReporterProvider = Provider<ListingEventReporter>(
  (ref) => ListingEventReporter(ref.watch(apiClientProvider)),
);
