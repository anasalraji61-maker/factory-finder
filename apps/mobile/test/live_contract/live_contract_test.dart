import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/assistant/assistant_repository.dart';
import 'package:factory_finder/features/deals/deals_repository.dart';
import 'package:factory_finder/features/discover/data/discover_models.dart';
import 'package:factory_finder/features/discover/data/discover_repository.dart';
import 'package:factory_finder/features/feed/feed_repository.dart';
import 'package:factory_finder/features/freight/data/freight_repository.dart';
import 'package:factory_finder/features/logistics/data/logistics_repository.dart';
import 'package:factory_finder/features/logistics/data/quote_request.dart';
import 'package:factory_finder/features/messages/data/messages_repository.dart';
import 'package:factory_finder/features/notify_prefs/notify_prefs_repository.dart';
import 'package:factory_finder/features/privacy/privacy_repository.dart';
import 'package:factory_finder/features/reco/reco_repository.dart';
import 'package:factory_finder/features/requests/data/mock_rfq.dart';
import 'package:factory_finder/features/requests/data/rfq_repository.dart';
import 'package:factory_finder/features/reviews/reviews_repository.dart';
import 'package:factory_finder/features/tracking/data/tracking_repository.dart';
import 'package:factory_finder/features/trust/trust_repository.dart';
import 'package:factory_finder/features/trust/verification_repository.dart';
import 'package:factory_finder/features/watchlist/data/watch_repository.dart';
import 'package:flutter_test/flutter_test.dart';

import 'live_support.dart';

/// Calls the REAL gateway (scripts/serve_stack.py) through the app's own
/// dio-based repositories and checks that the Dart models still parse what the
/// backend really sends. Every mismatch is collected and printed in one report.
/// Each pass runs twice: plain, and with unknown extra fields injected into
/// every JSON object (the parsers must tolerate them).
Future<void> _suite(ContractReport r, String mode, String baseUrl, LiveInfo info) async {
  final extra = mode == 'extra-fields';
  final buyer = liveClient(baseUrl, info, 'buyer', extraFields: extra);
  final supplier = liveClient(baseUrl, info, 'supplier', extraFields: extra);

  final discover = DiscoverRepository(buyer);

  await r.check(mode, 'discover: search', (c) async {
    final page = await discover.search(const ListingQuery(query: 'injection molding machine'));
    c.need(page.items, 'items');
    for (final l in page.items.take(5)) {
      c.need(l.id, 'listing.id');
      c.need(l.title, 'listing.title');
      c.need(l.price.min.amount, 'listing.price.min.amount');
      c.need(l.price.min.currency, 'listing.price.min.currency');
      c.need(l.supplier.id, 'listing.supplier.id');
      c.need(l.supplier.name, 'listing.supplier.name');
    }
  });

  await r.check(mode, 'discover: search sorted by trust + trending', (c) async {
    final page = await discover.search(const ListingQuery(sort: SortOption.trust));
    c.need(page.items, 'items');
    c.need(await discover.trending(), 'trending');
  });

  await r.check(mode, 'discover: categories', (c) async {
    final cats = await discover.categories();
    c.need(cats, 'categories');
    for (final n in cats) {
      c.need(n.slug, 'category.slug');
    }
  });

  await r.check(mode, 'discover: listing detail', (c) async {
    if (!c.seeded(info.listingId, 'listing_id')) return;
    final l = await discover.getListing(info.listingId!);
    c.need(l.id, 'id');
    c.need(l.title, 'title');
    c.need(l.supplier.id, 'supplier.id');
    c.need(l.source, 'source');
  });

  await r.check(mode, 'discover: native listing detail (supplier-owned)', (c) async {
    if (!c.seeded(info.nativeListingId, 'native_listing_id (published)')) return;
    final l = await discover.getListing(info.nativeListingId!);
    c.need(l.id, 'id');
    c.need(l.supplier.id, 'supplier.id');
    if (l.source != 'native') c.need(null, 'source == native (got ${l.source})');
  });

  await r.check(mode, 'discover: supplier + trust score', (c) async {
    if (!c.seeded(info.supplierId, 'external_supplier_id')) return;
    final s = await discover.getSupplier(info.supplierId!);
    c.need(s.id, 'supplier.id');
    c.need(s.name, 'supplier.name');
    final t = await discover.getTrust(info.supplierId!);
    c.need(t.supplierId, 'trust.supplier_id');
    c.need(t.factors, 'trust.factors');
    c.need(t.score, 'trust.score');
  });

  await r.check(mode, 'trust: history + verification badge', (c) async {
    if (!c.seeded(info.supplierId, 'external_supplier_id')) return;
    final h = await LiveTrustExtrasRepository(buyer).history(info.supplierId!);
    c.need(h, 'trust history points');
    final v = await LiveVerificationRepository(buyer).publicBadge(info.supplierId!);
    c.need(v.supplierId, 'verification.supplier_id');
    c.need(v.level, 'verification.level');
    c.need(v.label, 'verification.label');
  });

  await r.check(mode, 'logistics: landed-cost quote', (c) async {
    final logistics = LogisticsRepository(buyer);
    final q = await logistics.calculate(const QuoteRequest(
      goodsValue: 5000,
      weightKg: 3000,
      volumeM3: 30,
      origin: Location(countryCode: 'CN', city: 'Shanghai'),
      destination: Location(countryCode: 'IQ', city: 'Baghdad'),
    ));
    c.need(q.id, 'quote.id');
    c.need(q.currency, 'quote.currency');
    c.need(q.options, 'quote.options');
    for (final o in q.options) {
      c.need(o.lines, 'option.lines (${o.mode})');
      c.need(o.total.min.amount, 'option.total.min.amount (${o.mode})');
    }
    if (info.listingId != null) await logistics.prefill(info.listingId!);
  });

  await r.check(mode, 'rfq: requests, offers', (c) async {
    if (!c.seeded(info.requestId, 'request_id')) return;
    final rfq = RfqRepository(buyer);
    final list = await rfq.list(const RfqFilter(mine: true));
    if (!list.items.any((x) => x.id == info.requestId)) {
      c.need(null, 'seeded request in /v1/requests?scope=mine');
    }
    final one = await rfq.get(info.requestId!);
    c.need(one.title, 'request.title');
    final offers = await rfq.offers(info.requestId!);
    c.need(offers, 'offers');
    for (final o in offers) {
      c.need(o.id, 'offer.id');
      c.need(o.unitPrice.amount, 'offer.price.amount');
    }
    await RfqRepository(buyer).list(const RfqFilter(mine: false));
  });

  await r.check(mode, 'deals: list, get, by request, events', (c) async {
    if (!c.seeded(info.dealId, 'deal_id')) return;
    final deals = LiveDealsRepository(buyer);
    final page = await deals.listDeals(role: 'buyer');
    if (!page.items.any((d) => d.id == info.dealId)) {
      c.need(null, 'seeded deal in /v1/deals?role=buyer');
    }
    final d = await deals.get(info.dealId!);
    c.need(d.commission.amount, 'deal.commission.amount');
    c.need(d.subtotal.amount, 'deal.subtotal.amount');
    c.need(d.status, 'deal.status');
    c.need(d.payment, 'deal.payment');
    final byReq = await deals.dealForRequest(info.requestId!);
    c.need(byReq, 'deal for request');
    final ev = await deals.events(info.dealId!);
    c.need(ev, 'deal events');
    // the supplier sees the same deal
    await LiveDealsRepository(supplier).listDeals(role: 'supplier');
  });

  await r.check(mode, 'messaging: conversations + messages + attachments', (c) async {
    if (!c.seeded(info.conversationId, 'conversation_id')) return;
    final repo = LiveMessagingRepository(supplier, () => info.user('supplier')['id'] as String?);
    final convs = await repo.conversations();
    c.need(convs, 'conversations');
    for (final cv in convs) {
      c.need(cv.id, 'conversation.id');
      c.need(cv.participantId, 'conversation.participantId');
    }
    final msgs = await repo.messages(info.conversationId!);
    c.need(msgs, 'messages');
    final withAtt = msgs.where((m) => m.attachments.isNotEmpty).toList();
    c.need(withAtt, 'message.attachments (seeded attachment message)');
    for (final m in withAtt) {
      for (final a in m.attachments) {
        c.need(a.url, 'attachment.url');
      }
    }
    // the buyer's list carries the last message preview, incl. lastAttachments
    await LiveMessagingRepository(buyer, () => info.buyerId).conversations();
  });

  await r.check(mode, 'notifications: watchlist, alerts, prefs', (c) async {
    final repo = LiveWatchlistRepository(buyer);
    final w = await repo.watchlist();
    c.need(w, 'watchlist');
    for (final x in w) {
      c.need(x.id, 'watch.id');
    }
    final alerts = await repo.alerts();
    c.need(alerts.items, 'alerts (seeded shipment alert)');
    for (final a in alerts.items) {
      c.need(a.id, 'alert.id');
      c.need(a.title, 'alert.title');
    }
    await repo.unreadCount();
    final prefs = await LiveNotifyPrefsRepository(buyer).get();
    c.need(prefs.timezone, 'prefs.timezone');
  });

  await r.check(mode, 'tracking: list + detail', (c) async {
    if (!c.seeded(info.shipmentId, 'shipment_id')) return;
    final repo = LiveTrackingRepository(buyer);
    final list = await repo.shipments();
    c.need(list, 'shipments');
    final s = await repo.shipment(info.shipmentId!);
    c.need(s.reference, 'shipment.reference');
    c.need(s.events, 'shipment.events');
  });

  await r.check(mode, 'reviews: summary + list', (c) async {
    if (!c.seeded(info.supplierId, 'external_supplier_id')) return;
    final repo = LiveReviewsRepository(buyer);
    final s = await repo.summary(info.supplierId!);
    c.need(s.count, 'summary.count');
    final p = await repo.list(info.supplierId!);
    c.need(p.total, 'reviews.total');
  });

  await r.check(mode, 'feed: home, trending, supplier posts', (c) async {
    final repo = LiveFeedRepository(buyer);
    final home = await repo.home();
    c.need(home.items, 'feed home items');
    final trending = await repo.trending();
    c.need(trending.items, 'feed trending items');
    for (final p in trending.items) {
      c.need(p.id, 'post.id');
      c.need(p.supplierId, 'post.supplier_id');
      c.need(p.body, 'post.body');
    }
    if (info.claimedSupplierId != null) {
      c.need((await repo.supplierPosts(info.claimedSupplierId!)).items, 'supplier posts');
    }
  });

  await r.check(mode, 'freight: requests list + whoami', (c) async {
    final repo = LiveFreightRepository(buyer);
    final mine = await repo.myRequests();
    c.need(mine.items, 'freight requests (seeded)');
    for (final q in mine.items) {
      c.need(q.id, 'freight request.id');
      c.need(q.originCountry, 'freight request.origin_country');
    }
    if (info.freightRequestId != null) {
      c.need((await repo.getRequest(info.freightRequestId!)).id, 'freight request detail');
    }
    await repo.whoami();
  });

  await r.check(mode, 'reco: price history, similar, recommendations', (c) async {
    if (!c.seeded(info.listingId, 'listing_id')) return;
    final repo = LiveRecoRepository(buyer);
    final h = await repo.priceHistory(info.listingId!);
    c.need(h.listingId, 'price_history.listing_id');
    c.need(h.currency, 'price_history.currency');
    final sim = await repo.similar(info.listingId!);
    for (final i in sim.items) {
      c.need(i.listing.id, 'similar.listing.id');
    }
    final rec = await repo.recommendations(refs: [info.listingId!]);
    for (final i in rec.items) {
      c.need(i.listing.id, 'recommendation.listing.id');
    }
  });

  await r.check(mode, 'assistant: reply cards', (c) async {
    final a = await AssistantRepository(buyer)
        .ask('ابي ٥٠٠ كرسي بلاستك من الصين الى اربيل');
    c.need(a.intent, 'answer.intent');
    c.need(a.cards, 'answer.cards');
    for (final card in a.cards) {
      c.need(card.type, 'card.type');
    }
  });

  await r.check(mode, 'privacy: me/export', (c) async {
    final e = await LivePrivacyRepository(buyer).exportData();
    c.need(e.json, 'export json');
  });
}

void main() {
  if (!liveEnabled) {
    test('live contract (skipped)', () {}, skip: kLiveSkipReason);
    return;
  }

  final report = ContractReport();
  late LiveInfo info;
  final baseUrl = liveBaseUrl!;

  setUpAll(() {
    info = LiveInfo.load();
    final errs = info.json['seed_errors'];
    if (errs is Map && errs.isNotEmpty) {
      // ignore: avoid_print
      print('serve_stack seed errors: $errs');
    }
  });

  test('plain responses parse into the app models', () async {
    await _suite(report, 'plain', baseUrl, info);
  }, timeout: const Timeout(Duration(minutes: 3)));

  test('unknown extra fields are tolerated', () async {
    await _suite(report, 'extra-fields', baseUrl, info);
  }, timeout: const Timeout(Duration(minutes: 3)));

  test('no contract mismatches', () {
    // ignore: avoid_print
    print(report.render());
    if (report.problems.isNotEmpty) {
      fail('${report.problems.length} contract mismatch(es):\n${report.render()}');
    }
  });
}
