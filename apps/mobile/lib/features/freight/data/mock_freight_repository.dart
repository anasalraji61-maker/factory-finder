import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/api/auth.dart' show kMockUserId;
import 'package:factory_finder/features/freight/data/freight_decimal.dart';
import 'package:factory_finder/features/freight/data/freight_drafts.dart';
import 'package:factory_finder/features/freight/data/freight_models.dart';
import 'package:factory_finder/features/freight/data/freight_repository.dart';
import 'package:factory_finder/features/logistics/data/quote_request.dart' show FreightOverride;

/// Deterministic in-memory freight marketplace for mock mode and tests.
///
/// One session user ([userId]) acts as buyer and, after applying, as an
/// (auto-approved unless [autoApprove] is false) forwarder. Everything that
/// depends on time goes through [clock]; ids are counters.
class MockFreightRepository implements FreightRepository {
  MockFreightRepository({
    DateTime Function()? clock,
    this.userId = kMockUserId,
    this.autoApprove = true,
    this.seed = true,
    this.delayMs = 0,
  }) : _clock = clock ?? (() => DateTime.now().toUtc()) {
    if (seed) _seed();
  }

  final DateTime Function() _clock;
  final String userId;
  final bool autoApprove;
  final bool seed;
  final int delayMs;

  final Map<String, ShipmentRequest> _requests = {};
  final Map<String, String> _owner = {}; // request id -> buyer user id
  final Map<String, Quote> _quotes = {};
  final Map<String, Forwarder> _forwarders = {};
  final Map<String, String> _forwarderUser = {}; // forwarder id -> user id
  final Map<String, int> _ratingSum = {};
  final Map<String, int> _ratingCount = {};
  final Set<String> _rated = {};
  final List<FreightApplication> _applications = [];
  final List<String> reports = []; // "kind:id:reason", for tests
  int _seq = 1000;

  Future<void> _wait() async {
    if (delayMs > 0) await mockDelay(delayMs);
  }

  ApiException _err(int status, String code) =>
      ApiException(status: status, code: code, message: code);

  String _id(String prefix) => '${prefix}_${_seq++}';

  // ---------------------------------------------------------------- seed

  void _seed() {
    final now = _clock();
    Forwarder fwd(String id, String user, String name, String cc, int sum, int count, int jobs) {
      final f = Forwarder(
        id: id,
        companyName: name,
        countryCode: cc,
        lanes: const [Lane(origin: 'CN', destination: 'IQ')],
        modes: const ['sea', 'air'],
        incoterms: const ['FOB', 'EXW', 'CIF'],
        certifications: const ['FIATA'],
        rating: FreightRating(
          average: count == 0 ? null : FreightDecimal.formatScaled(sum * 100 ~/ count, 2),
          count: count,
        ),
        completedJobs: jobs,
        status: 'active',
      );
      _forwarders[id] = f;
      _forwarderUser[id] = user;
      _ratingSum[id] = sum;
      _ratingCount[id] = count;
      return f;
    }

    fwd('fw_silk', 'usr_fwd_1', 'Silk Route Logistics', 'CN', 54, 12, 41);
    fwd('fw_gulf', 'usr_fwd_2', 'Gulf Cargo Services', 'AE', 12, 3, 9);
    fwd('fw_orient', 'usr_fwd_3', 'Orient Express Freight', 'TR', 0, 0, 0);

    ShipmentRequest req(
      String id,
      String owner,
      String oc,
      String op,
      String dc,
      String dp,
      String cargo,
      String mode,
      String incoterm, {
      String weight = '18000.000',
      String? container = '40HC',
      int daysAgo = 2,
      String status = 'open',
      String? outcome,
    }) {
      final r = ShipmentRequest(
        id: id,
        originCountry: oc,
        originPlace: op,
        destinationCountry: dc,
        destinationPlace: dp,
        cargoDescription: cargo,
        weightKg: weight,
        volumeCbm: '58.000',
        mode: mode,
        containerType: container,
        containerCount: container == null ? null : 1,
        incoterm: incoterm,
        readyDate: formatIsoDate(now.add(const Duration(days: 14))),
        currency: 'USD',
        status: status,
        outcome: outcome,
        expiresAt: now.add(const Duration(days: 12)),
        buyerId: owner,
        createdAt: now.subtract(Duration(days: daysAgo)),
        closedAt: status == 'closed' ? now.subtract(const Duration(days: 1)) : null,
      );
      _requests[id] = r;
      _owner[id] = owner;
      return r;
    }

    Quote quote(
      String id,
      String reqId,
      String fid,
      String amount,
      int transit,
      int minutesAgo, {
      List<QuoteLine> lines = const [],
      String status = 'submitted',
      List<String> inc = const ['Ocean freight', 'Origin handling'],
      List<String> exc = const ['Insurance'],
    }) {
      final f = _forwarders[fid]!;
      _quotes[id] = Quote(
        id: id,
        requestId: reqId,
        forwarderId: fid,
        amount: amount,
        currency: 'USD',
        transitDays: transit,
        validUntil: now.add(const Duration(days: 10)),
        valid: true,
        inclusions: inc,
        exclusions: exc,
        breakdown: lines,
        status: status,
        createdAt: now.subtract(Duration(minutes: minutesAgo)),
        updatedAt: now.subtract(Duration(minutes: minutesAgo)),
        forwarder: _summary(f),
      );
      return _quotes[id]!;
    }

    req('fr_100', userId, 'CN', 'Shenzhen', 'IQ', 'Baghdad', 'LED lighting, palletized', 'sea', 'FOB');
    quote('fq_100_1', 'fr_100', 'fw_silk', '3200.00', 32, 300, lines: const [
      QuoteLine(label: 'Ocean freight', amount: '2800.00'),
      QuoteLine(label: 'Destination handling', amount: '400.00'),
    ]);
    quote('fq_100_2', 'fr_100', 'fw_gulf', '2950.00', 38, 200);
    quote('fq_100_3', 'fr_100', 'fw_orient', '3500.00', 28, 100);
    _requests['fr_100'] = _requests['fr_100']!.copyWith(quoteCount: 3);

    req('fr_101', userId, 'CN', 'Ningbo', 'IQ', 'Basra', 'Textile rolls', 'sea', 'FOB',
        status: 'closed', outcome: 'completed', daysAgo: 20);
    quote('fq_101_1', 'fr_101', 'fw_silk', '2750.00', 30, 5000, status: 'accepted');
    _requests['fr_101'] = _requests['fr_101']!.copyWith(
      quoteCount: 1,
      awardedQuoteId: 'fq_101_1',
      awardedAt: now.subtract(const Duration(days: 15)),
    );

    req('fr_102', userId, 'CN', 'Guangzhou', 'IQ', 'Baghdad', 'Furniture parts', 'sea', 'EXW',
        status: 'awarded', daysAgo: 6);
    quote('fq_102_1', 'fr_102', 'fw_gulf', '4100.00', 35, 4000, status: 'accepted');
    _requests['fr_102'] = _requests['fr_102']!.copyWith(
      quoteCount: 1,
      awardedQuoteId: 'fq_102_1',
      awardedAt: now.subtract(const Duration(days: 3)),
    );

    req('fr_200', 'usr_other_1', 'CN', 'Shanghai', 'IQ', 'Erbil', 'Spare parts for packaging machines', 'sea', 'FOB', daysAgo: 1);
    req('fr_201', 'usr_other_2', 'TR', 'Mersin', 'IQ', 'Baghdad', 'Ceramic tiles', 'road', 'DAP', container: null, daysAgo: 3);
  }

  ForwarderSummary _summary(Forwarder f) => ForwarderSummary(
        id: f.id,
        companyName: f.companyName,
        countryCode: f.countryCode,
        rating: f.rating,
        completedJobs: f.completedJobs,
      );

  // ------------------------------------------------------------- helpers

  ShipmentRequest _live(String id) {
    final r = _requests[id];
    if (r == null) throw _err(404, 'not_found');
    if (r.isOpen && r.expiresAt != null && !r.expiresAt!.isAfter(_clock())) {
      final e = r.copyWith(status: 'expired');
      _requests[id] = e;
      return e;
    }
    return r;
  }

  /// What [viewer] is allowed to see of [r] (buyer-only fields hidden).
  ShipmentRequest _view(ShipmentRequest r, {bool inbox = false}) {
    final mine = _owner[r.id] == userId;
    final myFwd = _myForwarder();
    final winner = myFwd != null &&
        r.awardedQuoteId != null &&
        _quotes[r.awardedQuoteId]?.forwarderId == myFwd.id;
    final quoted = myFwd != null &&
        _quotes.values.any((q) => q.requestId == r.id && q.forwarderId == myFwd.id);
    final full = mine || winner;
    return r.copyWith(hideBuyer: !full, hasQuoted: inbox ? quoted : false);
  }

  Forwarder? _myForwarder() {
    for (final e in _forwarderUser.entries) {
      if (e.value == userId) return _forwarders[e.key];
    }
    return null;
  }

  bool _matches(Forwarder f, ShipmentRequest r) =>
      f.lanes.any((l) =>
          (l.origin == '*' || l.origin == r.originCountry) &&
          (l.destination == '*' || l.destination == r.destinationCountry)) &&
      f.modes.contains(r.mode) &&
      f.incoterms.contains(r.incoterm);

  static bool _unsafe(String? s) {
    if (s == null) return false;
    final t = s.toLowerCase();
    return t.contains('http') ||
        t.contains('www.') ||
        t.contains('@') ||
        RegExp(r'\d{7,}').hasMatch(t.replaceAll(RegExp(r'[\s\-+]'), ''));
  }

  void _screen(Iterable<String?> texts) {
    if (texts.any(_unsafe)) throw _err(422, 'content_rejected');
  }

  FreightPage<T> _page<T>(List<T> all, String? cursor, int limit) {
    var start = 0;
    if (cursor != null && cursor.isNotEmpty) {
      final c = int.tryParse(cursor);
      if (c == null || c < 0) throw _err(422, 'invalid_cursor');
      start = c;
    }
    final n = limit.clamp(1, 50);
    final end = (start + n) > all.length ? all.length : start + n;
    final items = start >= all.length ? <T>[] : all.sublist(start, end);
    return FreightPage<T>(items: items, nextCursor: end < all.length ? '$end' : null);
  }

  int _newest(ShipmentRequest a, ShipmentRequest b) {
    final c = (b.createdAt ?? DateTime(0)).compareTo(a.createdAt ?? DateTime(0));
    return c != 0 ? c : b.id.compareTo(a.id);
  }

  // ------------------------------------------------------------ identity

  @override
  Future<Whoami> whoami() async {
    await _wait();
    final f = _myForwarder();
    return Whoami(userId: userId, forwarderId: f?.id, forwarderStatus: f?.status);
  }

  @override
  Future<FreightApplication> apply(ApplicationDraft draft) async {
    await _wait();
    if (_myForwarder() != null) throw _err(409, 'already_forwarder');
    if (_applications.any((a) => a.isPending)) throw _err(409, 'application_pending');
    if (_applications.length >= 5) throw _err(409, 'application_limit_reached');
    _screen([draft.companyName, draft.description, ...draft.certifications]);
    final invalid = draft.validate();
    if (invalid != null) throw _err(422, 'validation_error');
    final now = _clock();
    var app = FreightApplication(
      id: _id('fa'),
      companyName: draft.companyName.trim(),
      countryCode: draft.countryCode,
      description: draft.description.trim().isEmpty ? null : draft.description.trim(),
      lanes: draft.lanes,
      modes: draft.modes,
      incoterms: draft.incoterms,
      certifications: draft.certifications,
      status: 'pending',
      createdAt: now,
    );
    if (autoApprove) {
      final fid = _id('fw');
      final f = Forwarder(
        id: fid,
        companyName: app.companyName,
        countryCode: app.countryCode,
        description: app.description,
        lanes: app.lanes,
        modes: app.modes,
        incoterms: app.incoterms,
        certifications: app.certifications,
        status: 'active',
      );
      _forwarders[fid] = f;
      _forwarderUser[fid] = userId;
      _ratingSum[fid] = 0;
      _ratingCount[fid] = 0;
      app = FreightApplication(
        id: app.id,
        companyName: app.companyName,
        countryCode: app.countryCode,
        description: app.description,
        lanes: app.lanes,
        modes: app.modes,
        incoterms: app.incoterms,
        certifications: app.certifications,
        status: 'approved',
        forwarderId: fid,
        createdAt: now,
        reviewedAt: now,
      );
    }
    _applications.insert(0, app);
    return app;
  }

  @override
  Future<FreightPage<FreightApplication>> myApplications() async {
    await _wait();
    return FreightPage(items: List.of(_applications));
  }

  Forwarder _requireForwarder() {
    final f = _myForwarder();
    if (f == null) throw _err(403, 'forwarder_required');
    if (f.status == 'suspended') throw _err(403, 'forwarder_suspended');
    return f;
  }

  @override
  Future<FreightPage<ShipmentRequest>> inbox({String? cursor, int limit = 20}) async {
    await _wait();
    final f = _requireForwarder();
    final list = [
      for (final id in _requests.keys.toList())
        if (_owner[id] != userId &&
            _live(id).isOpen &&
            _matches(f, _requests[id]!))
          _requests[id]!,
    ]..sort(_newest);
    final page = _page(list, cursor, limit);
    return FreightPage(
      items: [for (final r in page.items) _view(r, inbox: true)],
      nextCursor: page.nextCursor,
    );
  }

  @override
  Future<FreightPage<Quote>> myQuotes({String? status, String? cursor, int limit = 20}) async {
    await _wait();
    final f = _requireForwarder();
    final list = [
      for (final q in _quotes.values)
        if (q.forwarderId == f.id && (status == null || q.status == status)) q,
    ]..sort((a, b) {
        final c = (b.createdAt ?? DateTime(0)).compareTo(a.createdAt ?? DateTime(0));
        return c != 0 ? c : b.id.compareTo(a.id);
      });
    return _page(list, cursor, limit);
  }

  // --------------------------------------------------------------- buyer

  @override
  Future<ShipmentRequest> createRequest(RequestDraft draft) async {
    await _wait();
    final open = [
      for (final id in _requests.keys)
        if (_owner[id] == userId && _live(id).isOpen) id,
    ];
    if (open.length >= 50) throw _err(409, 'request_limit_reached');
    _screen([draft.originPlace, draft.destinationPlace, draft.cargoDescription]);
    final now = _clock();
    if (draft.validate(now) != null) throw _err(422, 'validation_error');
    final id = _id('fr');
    final w = FreightDecimal.canonical(draft.weightKg, 3);
    final v = FreightDecimal.canonical(draft.volumeCbm, 3);
    final container = (draft.mode == 'sea' || draft.mode == 'rail') ? draft.containerType : null;
    final r = ShipmentRequest(
      id: id,
      originCountry: draft.originCountry,
      originPlace: draft.originPlace.trim(),
      destinationCountry: draft.destinationCountry,
      destinationPlace: draft.destinationPlace.trim(),
      cargoDescription: draft.cargoDescription.trim(),
      hsCode: draft.hsCode.trim().isEmpty ? null : draft.hsCode.trim(),
      weightKg: w,
      volumeCbm: v,
      mode: draft.mode,
      containerType: container,
      containerCount: container == null ? null : (draft.containerCount ?? 1),
      incoterm: draft.incoterm,
      readyDate: formatIsoDate(draft.readyDate),
      currency: draft.currency,
      landedCostRef: draft.landedCostRef,
      status: 'open',
      expiresAt: now.add(Duration(days: draft.quoteDeadlineDays)),
      buyerId: userId,
      createdAt: now,
    );
    _requests[id] = r;
    _owner[id] = userId;
    return _view(r);
  }

  @override
  Future<FreightPage<ShipmentRequest>> myRequests({String? status, String? cursor, int limit = 20}) async {
    await _wait();
    final list = [
      for (final id in _requests.keys.toList())
        if (_owner[id] == userId && (status == null || _live(id).status == status))
          _requests[id]!,
    ]..sort(_newest);
    final page = _page(list, cursor, limit);
    return FreightPage(
      items: [for (final r in page.items) _view(r)],
      nextCursor: page.nextCursor,
    );
  }

  @override
  Future<ShipmentRequest> getRequest(String id) async {
    await _wait();
    final r = _live(id);
    final f = _myForwarder();
    final visible = _owner[id] == userId ||
        _quotes.values.any((q) => q.requestId == id && q.forwarderId == f?.id) ||
        (f != null && r.isOpen && _matches(f, r));
    if (!visible) throw _err(404, 'not_found');
    return _view(r, inbox: true);
  }

  ShipmentRequest _mine(String id) {
    final r = _live(id);
    if (_owner[id] != userId) throw _err(404, 'not_found');
    return r;
  }

  @override
  Future<ShipmentRequest> closeRequest(String id) async {
    await _wait();
    final r = _mine(id);
    if (r.status == 'closed') return _view(r);
    if (r.status == 'expired') throw _err(409, 'request_expired');
    final closed = r.copyWith(
      status: 'closed',
      outcome: r.isAwarded ? 'completed' : 'cancelled',
      closedAt: _clock(),
    );
    _requests[id] = closed;
    if (closed.outcome == 'completed') {
      final q = _quotes[r.awardedQuoteId];
      final f = q == null ? null : _forwarders[q.forwarderId];
      if (f != null) {
        _forwarders[f.id] = Forwarder(
          id: f.id,
          companyName: f.companyName,
          countryCode: f.countryCode,
          description: f.description,
          lanes: f.lanes,
          modes: f.modes,
          incoterms: f.incoterms,
          certifications: f.certifications,
          rating: f.rating,
          completedJobs: f.completedJobs + 1,
          status: f.status,
        );
      }
    }
    return _view(closed);
  }

  // ---------------------------------------------------------- comparison

  @override
  Future<Comparison> compare(String requestId, {String sort = 'score'}) async {
    await _wait();
    final r = _mine(requestId);
    final now = _clock();
    final excluded = <ExcludedQuote>[];
    final eligible = <Quote>[];
    final all = _quotes.values.where((q) => q.requestId == requestId).toList()
      ..sort((a, b) => (a.createdAt ?? DateTime(0)).compareTo(b.createdAt ?? DateTime(0)));
    for (final q in all) {
      final ok = q.status == 'submitted' || (q.isAccepted && r.status != 'open');
      if (!ok) continue;
      if (_forwarders[q.forwarderId]?.status == 'suspended') {
        excluded.add(ExcludedQuote(quoteId: q.id, reason: 'forwarder_suspended'));
      } else if (q.currency != r.currency) {
        excluded.add(ExcludedQuote(quoteId: q.id, reason: 'currency_mismatch'));
      } else if (q.validUntil != null && !q.validUntil!.isAfter(now) && !q.isAccepted) {
        excluded.add(ExcludedQuote(quoteId: q.id, reason: 'quote_expired'));
      } else {
        eligible.add(q);
      }
    }
    final items = _rank(eligible);
    return Comparison(
      requestId: requestId,
      requestStatus: r.status,
      currency: r.currency,
      sort: sort,
      items: sortComparisonItems(items, sort),
      excluded: excluded,
    );
  }

  double _shrunk(String fid) {
    final sum = _ratingSum[fid] ?? 0;
    final count = _ratingCount[fid] ?? 0;
    return (sum + 3 * 2) / (count + 2);
  }

  List<ComparisonItem> _rank(List<Quote> qs) {
    if (qs.isEmpty) return const [];
    const wp = 0.5, wt = 0.3, wr = 0.2;
    final cheapest = qs.map((q) => q.amountMinor ?? 1).reduce((a, b) => a < b ? a : b);
    final fastest = qs.map((q) => q.transitDays).reduce((a, b) => a < b ? a : b);
    final best = qs.map((q) => _shrunk(q.forwarderId)).reduce((a, b) => a > b ? a : b);
    double r3(double v) => (v * 1000).round() / 1000;
    String pct(double v) => '${(v * 100).round()}%';
    final rows = <ComparisonItem>[];
    for (final q in qs) {
      final ps = cheapest / (q.amountMinor ?? cheapest);
      final ts = fastest / q.transitDays;
      final sr = _shrunk(q.forwarderId);
      final rs = sr / 5;
      final score = ((100 * (wp * ps + wt * ts + wr * rs)) * 10).round() / 10;
      final count = _ratingCount[q.forwarderId] ?? 0;
      rows.add(ComparisonItem(
        rank: 0,
        score: score,
        price: ScorePart(value: r3(ps), weight: wp),
        transit: ScorePart(value: r3(ts), weight: wt),
        rating: ScorePart(value: r3(rs), weight: wr),
        adjustedRating: (sr * 100).round() / 100,
        badges: [
          if ((q.amountMinor ?? 0) == cheapest) 'cheapest',
          if (q.transitDays == fastest) 'fastest',
          if (sr == best && count > 0) 'top_rated',
        ],
        explanation: [
          'price ${pct(ps)} of best (weight ${pct(wp)})',
          'transit ${pct(ts)} of best (weight ${pct(wt)})',
          'rating ${(sr * 100).round() / 100}/5 after shrinking toward 3.0 (weight ${pct(wr)})',
        ],
        quote: q,
      ));
    }
    final ordered = sortComparisonItems(rows, 'score');
    return [for (var i = 0; i < ordered.length; i++) ordered[i].withRank(i + 1)];
  }

  @override
  Future<AcceptResult> acceptQuote(String quoteId) async {
    await _wait();
    final q = _quotes[quoteId];
    if (q == null) throw _err(404, 'not_found');
    final r = _mine(q.requestId);
    if (r.isAwarded || r.status == 'closed') {
      if (r.awardedQuoteId == quoteId) {
        return AcceptResult(request: _view(r), quote: _quotes[quoteId]!);
      }
      if (r.awardedQuoteId != null) throw _err(409, 'already_awarded');
    }
    if (r.status == 'expired') throw _err(409, 'request_expired');
    if (!r.isOpen) throw _err(409, 'request_not_open');
    if (!q.isSubmitted) throw _err(409, 'quote_not_available');
    if (q.validUntil != null && !q.validUntil!.isAfter(_clock())) {
      throw _err(409, 'quote_expired');
    }
    for (final other in _quotes.values.where((o) => o.requestId == r.id)) {
      if (other.id == quoteId) {
        _quotes[other.id] = other.copyWith(status: 'accepted', updatedAt: _clock());
      } else if (other.isSubmitted) {
        _quotes[other.id] = other.copyWith(status: 'rejected', updatedAt: _clock());
      }
    }
    final awarded = r.copyWith(
      status: 'awarded',
      awardedQuoteId: quoteId,
      awardedAt: _clock(),
    );
    _requests[r.id] = awarded;
    return AcceptResult(request: _view(awarded), quote: _quotes[quoteId]!);
  }

  @override
  Future<FreightOverride> landedCostInput(String quoteId) async {
    await _wait();
    final q = _quotes[quoteId];
    if (q == null) throw _err(404, 'not_found');
    final r = _mine(q.requestId);
    if (!q.isAccepted || r.awardedQuoteId != quoteId) {
      throw _err(409, 'quote_not_awarded');
    }
    // Always at least a day beyond the repository clock, so a consumer using a
    // slightly different clock never sees an already-expired override.
    final now = _clock();
    final floor = now.add(const Duration(days: 1));
    final until = q.validUntil ?? now.add(const Duration(days: 30));
    return FreightOverride(
      amount: q.amount,
      currency: q.currency,
      quoteId: q.id,
      validUntil: until.isAfter(floor) ? until : floor,
      modeFamily: r.mode,
    );
  }

  @override
  Future<RatingItem> rateForwarder(String requestId, int stars, {String? comment}) async {
    await _wait();
    final r = _mine(requestId);
    if (!r.isCompleted || r.awardedQuoteId == null) throw _err(409, 'not_completed');
    if (_rated.contains(requestId)) throw _err(409, 'already_rated');
    if (stars < 1 || stars > 5) throw _err(422, 'validation_error');
    _screen([comment]);
    final fid = _quotes[r.awardedQuoteId]!.forwarderId;
    _rated.add(requestId);
    _ratingSum[fid] = (_ratingSum[fid] ?? 0) + stars;
    _ratingCount[fid] = (_ratingCount[fid] ?? 0) + 1;
    final f = _forwarders[fid]!;
    _forwarders[fid] = Forwarder(
      id: f.id,
      companyName: f.companyName,
      countryCode: f.countryCode,
      description: f.description,
      lanes: f.lanes,
      modes: f.modes,
      incoterms: f.incoterms,
      certifications: f.certifications,
      rating: FreightRating(
        average: FreightDecimal.formatScaled(
            _ratingSum[fid]! * 100 ~/ _ratingCount[fid]!, 2),
        count: _ratingCount[fid]!,
      ),
      completedJobs: f.completedJobs,
      status: f.status,
    );
    return RatingItem(
      id: _id('frt'),
      requestId: requestId,
      forwarderId: fid,
      stars: stars,
      comment: comment?.trim().isEmpty ?? true ? null : comment!.trim(),
      createdAt: _clock(),
    );
  }

  // -------------------------------------------------------------- quotes

  void _checkDraft(ShipmentRequest r, QuoteDraft d) {
    _screen([...d.inclusions, ...d.exclusions, d.terms, ...d.breakdown.map((l) => l.label)]);
    if (d.currency != r.currency) throw _err(422, 'currency_mismatch');
    final invalid = d.validate();
    if (invalid == 'freight.v.breakdown_mismatch') throw _err(422, 'breakdown_mismatch');
    if (invalid != null) throw _err(422, 'validation_error');
  }

  Quote _build(String id, ShipmentRequest r, Forwarder f, QuoteDraft d, {Quote? old}) {
    final now = _clock();
    return Quote(
      id: id,
      requestId: r.id,
      forwarderId: f.id,
      amount: FreightDecimal.canonical(d.amount, 2)!,
      currency: d.currency,
      transitDays: d.transitDays,
      validUntil: now.add(Duration(days: d.validDays)),
      valid: true,
      inclusions: d.inclusions,
      exclusions: d.exclusions,
      breakdown: [
        for (final l in d.breakdown)
          QuoteLine(label: l.label.trim(), amount: FreightDecimal.canonical(l.amount, 2)!),
      ],
      terms: d.terms.trim().isEmpty ? null : d.terms.trim(),
      status: 'submitted',
      revision: (old?.revision ?? 0) + 1,
      createdAt: old?.createdAt ?? now,
      updatedAt: now,
      forwarder: _summary(f),
    );
  }

  @override
  Future<Quote> submitQuote(String requestId, QuoteDraft draft) async {
    await _wait();
    final f = _requireForwarder();
    final r = _live(requestId);
    if (!_matches(f, r) && _owner[requestId] != userId) throw _err(404, 'not_found');
    if (_owner[requestId] == userId) throw _err(403, 'own_request');
    if (!r.isOpen) throw _err(409, 'request_not_open');
    if (_quotes.values.any((q) => q.requestId == requestId && q.forwarderId == f.id)) {
      throw _err(409, 'quote_exists');
    }
    if (_quotes.values.where((q) => q.requestId == requestId && (q.isSubmitted || q.isAccepted)).length >= 50) {
      throw _err(409, 'quote_limit_reached');
    }
    _checkDraft(r, draft);
    final q = _build(_id('fq'), r, f, draft);
    _quotes[q.id] = q;
    _requests[r.id] = r.copyWith(quoteCount: r.quoteCount + 1);
    return q;
  }

  Quote _myQuote(String quoteId) {
    final f = _requireForwarder();
    final q = _quotes[quoteId];
    if (q == null || q.forwarderId != f.id) throw _err(404, 'not_found');
    return q;
  }

  @override
  Future<Quote> reviseQuote(String quoteId, QuoteDraft draft) async {
    await _wait();
    final q = _myQuote(quoteId);
    final r = _live(q.requestId);
    if (!r.isOpen) throw _err(409, 'request_not_open');
    if (q.isAccepted || q.status == 'rejected') throw _err(409, 'quote_final');
    _checkDraft(r, draft);
    final next = _build(q.id, r, _forwarders[q.forwarderId]!, draft, old: q);
    _quotes[q.id] = next;
    if (q.isWithdrawn) {
      _requests[r.id] = r.copyWith(quoteCount: r.quoteCount + 1);
    }
    return next;
  }

  @override
  Future<Quote> withdrawQuote(String quoteId) async {
    await _wait();
    final q = _myQuote(quoteId);
    if (q.isWithdrawn) return q;
    if (!q.isSubmitted) throw _err(409, 'quote_final');
    final w = q.copyWith(status: 'withdrawn', updatedAt: _clock());
    _quotes[q.id] = w;
    final r = _requests[q.requestId]!;
    _requests[r.id] = r.copyWith(quoteCount: r.quoteCount > 0 ? r.quoteCount - 1 : 0);
    return w;
  }

  // ------------------------------------------------------------- reports

  @override
  Future<void> reportRequest(String requestId, String reason, {String? details}) async {
    await _wait();
    _screen([details]);
    await getRequest(requestId);
    reports.add('request:$requestId:$reason');
  }

  @override
  Future<void> reportQuote(String quoteId, String reason, {String? details}) async {
    await _wait();
    final q = _quotes[quoteId];
    if (q == null) throw _err(404, 'not_found');
    _mine(q.requestId);
    reports.add('quote:$quoteId:$reason');
  }

  @override
  Future<void> reportForwarder(String forwarderId, String reason, {String? details}) async {
    await _wait();
    final f = _forwarders[forwarderId];
    if (f == null) throw _err(404, 'not_found');
    if (_forwarderUser[forwarderId] == userId) throw _err(422, 'cannot_report_own');
    final received = _quotes.values.any((q) =>
        q.forwarderId == forwarderId && _owner[q.requestId] == userId);
    if (!received) throw _err(404, 'not_found');
    reports.add('forwarder:$forwarderId:$reason');
  }
}
