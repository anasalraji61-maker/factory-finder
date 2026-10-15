import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:factory_finder/core/api/api_client.dart';
import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/freight/data/freight_decimal.dart';
import 'package:factory_finder/features/freight/data/freight_drafts.dart';
import 'package:factory_finder/features/freight/data/freight_errors.dart';
import 'package:factory_finder/features/freight/data/freight_models.dart';
import 'package:factory_finder/features/freight/data/freight_prefill.dart';
import 'package:factory_finder/features/freight/data/freight_repository.dart';
import 'package:factory_finder/features/freight/data/mock_freight_repository.dart';
import 'package:factory_finder/features/freight/freight_strings.dart';
import 'package:factory_finder/features/logistics/data/mock_quote_generator.dart';
import 'package:factory_finder/features/logistics/data/quote_request.dart';
import 'package:flutter_test/flutter_test.dart';

dynamic _load(String name) =>
    jsonDecode(File('test/fixtures/live/$name.json').readAsStringSync());

Map<String, dynamic> _obj(String name) =>
    Map<String, dynamic>.from(_load(name) as Map);

class _FakeAdapter implements HttpClientAdapter {
  _FakeAdapter(this.handler);

  final ResponseBody Function(RequestOptions o) handler;
  final List<RequestOptions> calls = [];

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    calls.add(options);
    return handler(options);
  }

  @override
  void close({bool force = false}) {}
}

ResponseBody _json(Object body, [int status = 200, Map<String, List<String>>? extra]) =>
    ResponseBody.fromString(
      jsonEncode(body),
      status,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
        ...?extra,
      },
    );

ApiClient _client(_FakeAdapter adapter) {
  final dio = Dio(BaseOptions(baseUrl: 'http://fake'))..httpClientAdapter = adapter;
  return ApiClient(baseUrl: 'http://fake', isMock: false, dio: dio);
}

DateTime _clock() => DateTime.utc(2026, 10, 15, 12);

RequestDraft _requestDraft({String cargo = 'Steel pipes', String mode = 'sea'}) => RequestDraft(
      originCountry: 'CN',
      originPlace: 'Ningbo',
      destinationCountry: 'IQ',
      destinationPlace: 'Basra',
      cargoDescription: cargo,
      weightKg: '1200',
      mode: mode,
      containerType: '20GP',
      containerCount: 2,
      incoterm: 'FOB',
      readyDate: DateTime.utc(2026, 11, 1),
    );

Matcher _apiError(int status, String code) => throwsA(
      isA<ApiException>()
          .having((e) => e.status, 'status', status)
          .having((e) => e.code, 'code', code),
    );

void main() {
  group('decimal', () {
    test('parses to scaled integers without floating point', () {
      expect(FreightDecimal.parseScaled('12.5', 2), 1250);
      expect(FreightDecimal.parseScaled('12', 2), 1200);
      expect(FreightDecimal.parseScaled('0.07', 2), 7);
      expect(FreightDecimal.parseScaled('12.345', 2), isNull);
      expect(FreightDecimal.parseScaled('12.345', 3), 12345);
      expect(FreightDecimal.parseScaled('-1', 2), isNull);
      expect(FreightDecimal.parseScaled('abc', 2), isNull);
      expect(FreightDecimal.parseScaled('', 2), isNull);
      expect(FreightDecimal.parseScaled('1e3', 2), isNull);
    });

    test('accepts Arabic-Indic digits, decimal comma and grouping', () {
      expect(FreightDecimal.parseScaled('١٢٫٥٠', 2), 1250);
      expect(FreightDecimal.parseScaled('12,5', 2), 1250);
      expect(FreightDecimal.parseScaled('1,234.50', 2), 123450);
      expect(FreightDecimal.parseScaled('۱۰', 2), 1000);
    });

    test('0.1 + 0.2 is exactly 0.30', () {
      final sum = FreightDecimal.sumScaled(['0.10', '0.20'], 2);
      expect(sum, 30);
      expect(FreightDecimal.formatScaled(sum!, 2), '0.30');
      expect(FreightDecimal.sumScaled(['1.00', 'x'], 2), isNull);
    });

    test('format and canonical', () {
      expect(FreightDecimal.formatScaled(5, 2), '0.05');
      expect(FreightDecimal.formatScaled(123456, 2), '1234.56');
      expect(FreightDecimal.formatScaled(7, 0), '7');
      expect(FreightDecimal.canonical('7', 2), '7.00');
      expect(FreightDecimal.canonical('18000.5', 3), '18000.500');
      expect(FreightDecimal.canonical('1.234', 2), isNull);
      expect(FreightDecimal.fromDouble(12.5, 3), '12.5');
      expect(FreightDecimal.fromDouble(18000, 3), '18000');
      expect(FreightDecimal.wire(12), '12');
      expect(FreightDecimal.wire(null), isNull);
    });
  });

  group('parsing (fixtures)', () {
    test('open request', () {
      final r = ShipmentRequest.fromJson(_obj('freight_request_open'));
      expect(r.id, 'fr_1a2b');
      expect(r.weightKg, '18000.000');
      expect(r.volumeCbm, '58.500');
      expect(r.containerType, '40HC');
      expect(r.containerCount, 1);
      expect(r.isOpen, isTrue);
      expect(r.expiresAt, DateTime.utc(2026, 10, 29, 12));
      expect(r.buyerId, startsWith('usr_'));
      expect(r.hasQuoted, isFalse);
    });

    test('request page: nulls, has_quoted and cursor', () {
      final p = FreightPage.fromJson(_load('freight_requests_page'), ShipmentRequest.fromJson);
      expect(p.items, hasLength(2));
      expect(p.nextCursor, 'MjA');
      expect(p.hasMore, isTrue);
      expect(p.items.first.hasQuoted, isTrue);
      expect(p.items.first.volumeCbm, isNull);
      final closed = p.items.last;
      expect(closed.isCompleted, isTrue);
      expect(closed.buyerId, isNull);
      expect(closed.weightKg, isNull);
      expect(closed.currency, 'EUR');
    });

    test('numbers on the wire are kept as exact strings', () {
      final r = ShipmentRequest.fromJson({
        'id': 'x',
        'weight_kg': 12.5,
        'volume_cbm': '0.250',
      });
      expect(r.weightKg, '12.5');
      expect(r.volumeCbm, '0.250');
    });

    test('quote with breakdown', () {
      final q = Quote.fromJson(_obj('freight_quote'));
      expect(q.amount, '3200.00');
      expect(q.amountMinor, 320000);
      expect(q.breakdown.map((l) => l.amount), ['2800.00', '400.00']);
      expect(q.revision, 2);
      expect(q.forwarder, isNull);
      expect(q.terms, isNull);
    });

    test('comparison, badges, excluded', () {
      final c = Comparison.fromJson(_load('freight_comparison'));
      expect(c.items, hasLength(3));
      expect(c.items.first.rank, 1);
      expect(c.items.first.score, 93.4);
      expect(c.items.first.price.weight, 0.5);
      expect(c.items.first.adjustedRating, 4.5);
      expect(c.items.first.quote.forwarder!.companyName, 'Silk Route Logistics');
      expect(c.items.first.quote.forwarder!.rating.average, '4.50');
      expect(c.items[1].quote.forwarder!.rating.average, isNull);
      expect(c.items[1].badges, ['cheapest']);
      expect(c.excluded.single.reason, 'quote_expired');
      expect(c.requestStatus, 'open');
    });

    test('accept result, application, whoami', () {
      final a = AcceptResult.fromJson(_load('freight_accept'));
      expect(a.request.isAwarded, isTrue);
      expect(a.request.awardedQuoteId, 'fq_1');
      expect(a.quote.isAccepted, isTrue);
      final app = FreightApplication.fromJson(_obj('freight_application'));
      expect(app.isPending, isTrue);
      expect(app.lanes, [
        const Lane(origin: 'CN', destination: 'IQ'),
        const Lane(origin: '*', destination: 'AE'),
      ]);
      expect(Whoami.fromJson(_load('freight_whoami_active')).isActive, isTrue);
      final none = Whoami.fromJson(_load('freight_whoami_none'));
      expect(none.forwarderStatus, isNull);
      expect(none.isActive, isFalse);
    });

    test('tolerates sparse json', () {
      final r = ShipmentRequest.fromJson({'id': 'x'});
      expect(r.status, 'open');
      expect(Quote.fromJson({'id': 'q'}).amount, '0');
      expect(FreightPage.fromJson(null, Quote.fromJson).items, isEmpty);
    });
  });

  group('comparison sort', () {
    final c = Comparison.fromJson(_load('freight_comparison'));
    List<String> ids(String sort) =>
        sortComparisonItems(c.items, sort).map((i) => i.quote.id).toList();

    test('each sort key', () {
      expect(ids('score'), ['fq_1', 'fq_2', 'fq_3']);
      expect(ids('price'), ['fq_2', 'fq_1', 'fq_3']);
      expect(ids('transit'), ['fq_3', 'fq_1', 'fq_2']);
      // rating: 4.5 first; the 3.0 ties break by lower price
      expect(ids('rating'), ['fq_1', 'fq_2', 'fq_3']);
    });

    test('does not mutate the input and keeps server ranks', () {
      final before = c.items.map((i) => i.quote.id).toList();
      final sorted = sortComparisonItems(c.items, 'price');
      expect(c.items.map((i) => i.quote.id).toList(), before);
      expect(sorted.first.rank, 2);
    });

    test('price ties break by transit, then earlier submission', () {
      ComparisonItem item(String id, String amount, int days, DateTime at) {
        final base = c.items.first;
        return ComparisonItem(
          rank: 1,
          score: 50,
          price: base.price,
          transit: base.transit,
          rating: base.rating,
          adjustedRating: 3,
          quote: Quote(
            id: id,
            requestId: 'r',
            forwarderId: 'f',
            amount: amount,
            currency: 'USD',
            transitDays: days,
            status: 'submitted',
            createdAt: at,
          ),
        );
      }

      final t0 = DateTime.utc(2026, 10, 1);
      final items = [
        item('c', '10.10', 5, t0.add(const Duration(minutes: 1))),
        item('b', '10.10', 5, t0),
        item('a', '10.10', 9, t0),
        item('d', '9.99', 20, t0),
      ];
      expect(sortComparisonItems(items, 'price').map((i) => i.quote.id), ['d', 'b', 'c', 'a']);
      // exact minor-unit compare: 10.10 vs 10.1 differ from a double pitfall
      expect(sortComparisonItems(items, 'transit').map((i) => i.quote.id).first, 'b');
    });
  });

  group('drafts and validators', () {
    test('request json: exact strings, container only for sea/rail', () {
      final j = _requestDraft().toJson();
      expect(j['weight_kg'], '1200.000');
      expect(j.containsKey('volume_cbm'), isFalse);
      expect(j['container_type'], '20GP');
      expect(j['container_count'], 2);
      expect(j['ready_date'], '2026-11-01');
      expect(j['currency'], 'USD');
      expect(j['quote_deadline_days'], 14);
      expect(j.containsKey('hs_code'), isFalse);
      expect(j.containsKey('landed_cost_ref'), isFalse);
      final air = _requestDraft(mode: 'air').toJson();
      expect(air.containsKey('container_type'), isFalse);
      expect(air.containsKey('container_count'), isFalse);
    });

    test('request validation', () {
      final now = _clock();
      expect(_requestDraft().validate(now), isNull);
      expect(_requestDraft(cargo: 'ab').validate(now), 'freight.v.cargo');
      expect(
        RequestDraft(
          originCountry: 'CN',
          originPlace: 'Ningbo',
          destinationCountry: 'IQ',
          destinationPlace: 'Basra',
          cargoDescription: 'Pipes',
          mode: 'sea',
          incoterm: 'FOB',
          readyDate: DateTime.utc(2026, 11, 1),
        ).validate(now),
        'freight.v.weight_or_volume',
      );
      expect(FreightValidators.decimal('1.2345', 3), 'freight.v.number_scale_3');
      expect(FreightValidators.decimal('0', 3), 'freight.v.number_scale_3');
      expect(FreightValidators.hs('8517.12'), isNull);
      expect(FreightValidators.hs('85'), 'freight.v.hs');
      expect(FreightValidators.hs('85x1'), 'freight.v.hs');
      expect(FreightValidators.readyDate(DateTime.utc(2026, 10, 14), now), 'freight.v.ready_date');
      expect(FreightValidators.readyDate(DateTime.utc(2026, 10, 15), now), isNull);
      expect(FreightValidators.readyDate(DateTime.utc(2027, 10, 15), now), isNull);
      expect(FreightValidators.readyDate(DateTime.utc(2027, 10, 16), now), 'freight.v.ready_date');
      expect(FreightValidators.currency('usd'), 'freight.v.currency');
    });

    test('quote breakdown must equal the total exactly', () {
      QuoteDraft d(String total, List<String> lines) => QuoteDraft(
            amount: total,
            currency: 'USD',
            transitDays: 10,
            breakdown: [
              for (var i = 0; i < lines.length; i++)
                QuoteLine(label: 'Line $i', amount: lines[i]),
            ],
          );
      expect(d('0.30', ['0.10', '0.20']).validate(), isNull);
      expect(d('0.30', ['0.10', '0.21']).validate(), 'freight.v.breakdown_mismatch');
      expect(d('100', ['60', '40.00']).validate(), isNull);
      expect(d('100', []).validate(), isNull);
      expect(d('100.005', []).validate(), 'freight.v.number_scale_2');
      expect(d('100', ['0']).validate(), 'freight.v.line_amount');
      expect(
        const QuoteDraft(amount: '5', currency: 'USD', transitDays: 0).validate(),
        'freight.v.transit',
      );
      expect(
        const QuoteDraft(amount: '5', currency: 'USD', transitDays: 3, inclusions: ['x'])
            .validate(),
        'freight.v.list_item',
      );
    });

    test('quote json uses canonical decimal strings', () {
      final j = const QuoteDraft(
        amount: '1200',
        currency: 'USD',
        transitDays: 20,
        inclusions: ['Ocean freight'],
        breakdown: [QuoteLine(label: ' Ocean ', amount: '1000.5'), QuoteLine(label: 'Local', amount: '199.5')],
        terms: ' ',
      ).toJson();
      expect(j['amount'], '1200.00');
      expect(j['terms'], isNull);
      expect(j['breakdown'], [
        {'label': 'Ocean', 'amount': '1000.50'},
        {'label': 'Local', 'amount': '199.50'},
      ]);
      expect(j['valid_days'], 14);
    });

    test('application validation and json', () {
      const ok = ApplicationDraft(
        companyName: 'Silk Route',
        countryCode: 'CN',
        lanes: [Lane(origin: 'CN', destination: '*')],
        modes: ['sea'],
        incoterms: ['FOB'],
        certifications: ['FIATA'],
      );
      expect(ok.validate(), isNull);
      expect(ok.toJson()['lanes'], [
        {'origin_country': 'CN', 'destination_country': '*'},
      ]);
      expect(ok.toJson().containsKey('description'), isFalse);
      const noLane = ApplicationDraft(
        companyName: 'Silk Route',
        countryCode: 'CN',
        lanes: [],
        modes: ['sea'],
        incoterms: ['FOB'],
      );
      expect(noLane.validate(), 'freight.v.lanes');
    });
  });

  group('prefill from landed cost', () {
    final request = QuoteRequest(
      goodsValue: 5000,
      weightKg: 18000,
      volumeM3: 58.5,
      origin: const Location(countryCode: 'CN', city: 'Shenzhen'),
      destination: const Location(countryCode: 'IQ', city: 'Baghdad'),
      incoterm: Incoterm.cif,
      hsCode: '940540',
    );

    test('carries route, quantities, incoterm and the quote reference', () {
      final quote = MockQuoteGenerator.generate(request, lang: 'en', now: _clock());
      final p = FreightPrefill.fromLandedCost(quote, inputs: request);
      expect(p.originCountry, 'CN');
      expect(p.originPlace, 'Shenzhen');
      expect(p.destinationCountry, 'IQ');
      expect(p.destinationPlace, 'Baghdad');
      expect(p.weightKg, '18000');
      expect(p.volumeCbm, '58.5');
      expect(p.incoterm, 'CIF');
      expect(p.hsCode, '940540');
      expect(p.landedCostRef, quote.id);
      expect(kFreightModes, contains(p.mode));
    });

    test('inputs for another route are ignored', () {
      final quote = MockQuoteGenerator.generate(request, lang: 'en', now: _clock());
      final other = QuoteRequest(
        goodsValue: 1,
        weightKg: 5,
        volumeM3: 0,
        origin: const Location(countryCode: 'TR'),
        destination: const Location(countryCode: 'IQ'),
      );
      final p = FreightPrefill.fromLandedCost(quote, inputs: other);
      expect(p.weightKg, isNull);
      expect(p.incoterm, isNull);
      expect(p.originCountry, 'CN');
    });

    test('transport mode mapping', () {
      expect(freightModeOf(TransportMode.seaFcl40hc), 'sea');
      expect(containerTypeOf(TransportMode.seaFcl40hc), '40HC');
      expect(containerTypeOf(TransportMode.seaLcl), 'LCL');
      expect(freightModeOf(TransportMode.air), 'air');
      expect(containerTypeOf(TransportMode.air), isNull);
      expect(freightModeOf(TransportMode.road), 'road');
      expect(freightModeOf(TransportMode.rail), 'rail');
    });
  });

  group('error mapping', () {
    ApiException ex(int s, String c, {int? retry}) =>
        ApiException(status: s, code: c, message: c, retryAfterSeconds: retry);

    test('every known code has an ar and en message', () {
      for (final code in kFreightErrorCodes) {
        final key = 'freight.err.$code';
        expect(freightStrings['ar']![key], isNotNull, reason: key);
        expect(freightStrings['en']![key], isNotNull, reason: key);
      }
      for (final key in [
        'freight.err.network',
        'freight.err.generic',
        'freight.err.rate_limited_seconds',
        'freight.err.rate_limited_minutes',
      ]) {
        expect(freightStrings['ar']![key], isNotNull, reason: key);
        expect(freightStrings['en']![key], isNotNull, reason: key);
      }
    });

    test('known codes map to their own key', () {
      for (final entry in {
        'already_awarded': 409,
        'forwarder_required': 403,
        'forwarder_suspended': 403,
        'content_rejected': 422,
        'currency_mismatch': 422,
        'breakdown_mismatch': 422,
        'request_limit_reached': 409,
        'quote_limit_reached': 409,
        'application_pending': 409,
        'application_limit_reached': 409,
        'already_rated': 409,
        'invalid_cursor': 422,
      }.entries) {
        expect(freightErrorKey(ex(entry.value, entry.key)), 'freight.err.${entry.key}');
      }
    });

    test('429 uses Retry-After', () {
      final s = freightErrorInfo(ex(429, 'rate_limited', retry: 30));
      expect(s.key, 'freight.err.rate_limited_seconds');
      expect(s.args, {'seconds': '30'});
      final m = freightErrorInfo(ex(429, 'rate_limited', retry: 600));
      expect(m.key, 'freight.err.rate_limited_minutes');
      expect(m.args, {'minutes': '10'});
      expect(freightErrorInfo(ex(429, 'rate_limited', retry: 150)).args, {'minutes': '3'});
      expect(freightErrorKey(ex(429, 'rate_limited')), 'freight.err.rate_limited');
      expect(freightErrorKey(ex(429, 'http_429')), 'freight.err.rate_limited');
    });

    test('unknown codes fall back to status, then generic; network separately', () {
      expect(freightErrorKey(ex(409, 'something_new')), 'freight.err.conflict');
      expect(freightErrorKey(ex(404, 'http_404')), 'freight.err.not_found');
      expect(freightErrorKey(ex(403, 'x')), 'freight.err.forbidden');
      expect(freightErrorKey(ex(401, 'x')), 'freight.err.unauthenticated');
      expect(freightErrorKey(ex(422, 'x')), 'freight.err.validation_error');
      expect(freightErrorKey(ex(500, 'x')), 'freight.err.generic');
      expect(freightErrorKey(ApiException(code: 'timeout', message: 't')), 'freight.err.network');
      expect(freightErrorKey(ApiException(code: 'network_error', message: 'n')), 'freight.err.network');
      expect(freightErrorKey(StateError('x')), 'freight.err.generic');
    });
  });

  group('live repository (fake Dio)', () {
    test('buyer calls hit the contract paths with exact bodies', () async {
      final adapter = _FakeAdapter((o) {
        if (o.path.endsWith('/comparison')) return _json(_load('freight_comparison'));
        if (o.path.endsWith('/accept')) return _json(_load('freight_accept'));
        if (o.path.endsWith('/rating')) {
          return _json({
            'id': 'rt_1',
            'request_id': 'fr_1a2b',
            'forwarder_id': 'fw_a1b2c3',
            'stars': 4,
            'comment': null,
            'created_at': '2026-10-16T08:00:00Z',
          }, 201);
        }
        if (o.path.endsWith('/report')) return _json({'status': 'received'}, 202);
        if (o.path == '/v1/freight/requests' && o.method == 'GET') {
          return _json(_load('freight_requests_page'));
        }
        return _json(_load('freight_request_open'), o.method == 'POST' ? 201 : 200);
      });
      final repo = LiveFreightRepository(_client(adapter));

      final created = await repo.createRequest(_requestDraft());
      expect(created.id, 'fr_1a2b');
      final page = await repo.myRequests(status: 'open', cursor: 'abc', limit: 5);
      expect(page.items, hasLength(2));
      await repo.getRequest('fr_1a2b');
      await repo.closeRequest('fr_1a2b');
      final cmp = await repo.compare('fr_1a2b', sort: 'price');
      expect(cmp.items, hasLength(3));
      final acc = await repo.acceptQuote('fq_1');
      expect(acc.request.isAwarded, isTrue);
      final rating = await repo.rateForwarder('fr_1a2b', 4, comment: '  ');
      expect(rating.stars, 4);
      await repo.reportQuote('fq_1', 'scam_or_fraud', details: 'bad');
      await repo.reportRequest('fr_1a2b', 'spam');
      await repo.reportForwarder('fw_a1b2c3', 'other');

      final c = adapter.calls;
      expect(c.map((o) => '${o.method} ${o.path}').toList(), [
        'POST /v1/freight/requests',
        'GET /v1/freight/requests',
        'GET /v1/freight/requests/fr_1a2b',
        'POST /v1/freight/requests/fr_1a2b/close',
        'GET /v1/freight/requests/fr_1a2b/comparison',
        'POST /v1/freight/quotes/fq_1/accept',
        'POST /v1/freight/requests/fr_1a2b/rating',
        'POST /v1/freight/quotes/fq_1/report',
        'POST /v1/freight/requests/fr_1a2b/report',
        'POST /v1/freight/forwarders/fw_a1b2c3/report',
      ]);
      expect(c[0].data, containsPair('weight_kg', '1200.000'));
      expect(c[0].data, containsPair('ready_date', '2026-11-01'));
      expect(c[1].queryParameters, {'status': 'open', 'cursor': 'abc', 'limit': 5});
      expect(c[4].queryParameters, {'sort': 'price'});
      expect(c[6].data, {'stars': 4});
      expect(c[7].data, {'reason': 'scam_or_fraud', 'details': 'bad'});
      expect(c[8].data, {'reason': 'spam'});
    });

    test('forwarder calls', () async {
      final adapter = _FakeAdapter((o) {
        if (o.path == '/v1/freight/me') return _json(_load('freight_whoami_active'));
        if (o.path.endsWith('/applications')) return _json(_load('freight_application'), 201);
        if (o.path.endsWith('/applications/mine')) {
          return _json({'items': [_load('freight_application')], 'next_cursor': null});
        }
        if (o.path.endsWith('/inbox')) return _json(_load('freight_requests_page'));
        if (o.path.endsWith('/forwarders/me/quotes')) {
          return _json({'items': [_load('freight_quote')], 'next_cursor': null});
        }
        return _json(_load('freight_quote'), o.method == 'POST' ? 201 : 200);
      });
      final repo = LiveFreightRepository(_client(adapter));
      expect((await repo.whoami()).isActive, isTrue);
      const draft = ApplicationDraft(
        companyName: 'Silk Route',
        countryCode: 'CN',
        lanes: [Lane(origin: 'CN', destination: 'IQ')],
        modes: ['sea'],
        incoterms: ['FOB'],
      );
      expect((await repo.apply(draft)).status, 'pending');
      expect((await repo.myApplications()).items, hasLength(1));
      expect((await repo.inbox(limit: 50)).items.first.hasQuoted, isTrue);
      expect((await repo.myQuotes(status: 'submitted')).items.single.id, 'fq_1');
      const q = QuoteDraft(amount: '3200', currency: 'USD', transitDays: 32);
      await repo.submitQuote('fr_1a2b', q);
      await repo.reviseQuote('fq_1', q);
      await repo.withdrawQuote('fq_1');
      final found = await findMyQuoteForRequest(repo, 'fr_1a2b');
      expect(found?.id, 'fq_1');
      expect(await findMyQuoteForRequest(repo, 'other'), isNull);

      expect(adapter.calls.map((o) => '${o.method} ${o.path}').toList().sublist(0, 8), [
        'GET /v1/freight/me',
        'POST /v1/freight/applications',
        'GET /v1/freight/applications/mine',
        'GET /v1/freight/forwarders/me/inbox',
        'GET /v1/freight/forwarders/me/quotes',
        'POST /v1/freight/requests/fr_1a2b/quotes',
        'PUT /v1/freight/quotes/fq_1',
        'POST /v1/freight/quotes/fq_1/withdraw',
      ]);
      final submit = adapter.calls[5].data as Map;
      expect(submit['amount'], '3200.00');
      expect(submit['currency'], 'USD');
      expect(adapter.calls[3].queryParameters, {'limit': 50});
    });

    test('error bodies and Retry-After become ApiException values', () async {
      final adapter = _FakeAdapter((o) {
        if (o.path.contains('accept')) return _json(_load('error_freight_already_awarded'), 409);
        if (o.path.contains('quotes')) {
          return _json(_load('error_freight_breakdown_mismatch'), 422);
        }
        if (o.path.contains('inbox')) {
          return _json(_load('error_freight_forwarder_required'), 403);
        }
        if (o.path.endsWith('requests')) {
          return _json(_load('error_freight_content_rejected'), 422);
        }
        return _json(_load('error_freight_rate_limited'), 429, {
          'retry-after': ['45'],
        });
      });
      final repo = LiveFreightRepository(_client(adapter));
      await expectLater(repo.acceptQuote('fq_2'), _apiError(409, 'already_awarded'));
      await expectLater(
        repo.submitQuote('fr', const QuoteDraft(amount: '5', currency: 'USD', transitDays: 3)),
        _apiError(422, 'breakdown_mismatch'),
      );
      await expectLater(repo.inbox(), _apiError(403, 'forwarder_required'));
      await expectLater(repo.createRequest(_requestDraft()), _apiError(422, 'content_rejected'));
      try {
        await repo.rateForwarder('fr_1', 5);
        fail('expected 429');
      } on ApiException catch (e) {
        expect(e.status, 429);
        expect(e.retryAfterSeconds, 45);
        expect(freightErrorInfo(e).args, {'seconds': '45'});
      }
    });

    test('non-object bodies are a bad_response error', () async {
      final adapter = _FakeAdapter((o) => _json([1, 2, 3]));
      final repo = LiveFreightRepository(_client(adapter));
      await expectLater(repo.whoami(), _apiError(502, 'bad_response'));
    });
  });

  group('mock repository', () {
    MockFreightRepository fresh({bool autoApprove = true}) =>
        MockFreightRepository(clock: _clock, autoApprove: autoApprove);

    test('seeded list is deterministic and paged newest first', () async {
      final repo = fresh();
      final all = await repo.myRequests();
      expect(all.items.map((r) => r.id), ['fr_100', 'fr_102', 'fr_101']);
      final p1 = await repo.myRequests(limit: 2);
      expect(p1.items.map((r) => r.id), ['fr_100', 'fr_102']);
      expect(p1.nextCursor, '2');
      final p2 = await repo.myRequests(limit: 2, cursor: p1.nextCursor);
      expect(p2.items.map((r) => r.id), ['fr_101']);
      expect(p2.nextCursor, isNull);
      await expectLater(repo.myRequests(cursor: 'zz'), _apiError(422, 'invalid_cursor'));
      final awarded = await repo.myRequests(status: 'awarded');
      expect(awarded.items.single.id, 'fr_102');
      // owner sees buyer/award ids; another buyer's request hides them
      expect(all.items.first.buyerId, 'usr_mock');
    });

    test('comparison ranks with the contract formula and badges', () async {
      final repo = fresh();
      final c = await repo.compare('fr_100');
      expect(c.items.map((i) => i.quote.id), ['fq_100_1', 'fq_100_2', 'fq_100_3']);
      expect(c.items.map((i) => i.score), [89.5, 86.5, 84.1]);
      expect(c.items.map((i) => i.rank), [1, 2, 3]);
      expect(c.items[0].badges, ['top_rated']);
      expect(c.items[1].badges, ['cheapest']);
      expect(c.items[2].badges, ['fastest']);
      expect(c.items[0].adjustedRating, 4.29);
      expect(c.items[2].adjustedRating, 3.0);
      final byPrice = await repo.compare('fr_100', sort: 'price');
      expect(byPrice.items.map((i) => i.quote.id), ['fq_100_2', 'fq_100_1', 'fq_100_3']);
      expect(byPrice.items.first.rank, 2);
      final byTransit = await repo.compare('fr_100', sort: 'transit');
      expect(byTransit.items.first.quote.id, 'fq_100_3');
    });

    test('accept is idempotent for the winner and already_awarded for others', () async {
      final repo = fresh();
      final first = await repo.acceptQuote('fq_100_1');
      expect(first.request.status, 'awarded');
      expect(first.request.awardedQuoteId, 'fq_100_1');
      expect(first.quote.status, 'accepted');
      final again = await repo.acceptQuote('fq_100_1');
      expect(again.quote.id, 'fq_100_1');
      await expectLater(repo.acceptQuote('fq_100_2'), _apiError(409, 'already_awarded'));
      final c = await repo.compare('fr_100');
      expect(c.items.map((i) => i.quote.id), ['fq_100_1']);
      await expectLater(repo.acceptQuote('nope'), _apiError(404, 'not_found'));
    });

    test('complete, then rate exactly once; cancel has no rating', () async {
      final repo = fresh();
      await expectLater(repo.rateForwarder('fr_102', 5), _apiError(409, 'not_completed'));
      await repo.acceptQuote('fq_100_2');
      await expectLater(repo.rateForwarder('fr_100', 5), _apiError(409, 'not_completed'));
      final closed = await repo.closeRequest('fr_100');
      expect(closed.status, 'closed');
      expect(closed.outcome, 'completed');
      expect((await repo.closeRequest('fr_100')).outcome, 'completed');
      final r = await repo.rateForwarder('fr_100', 4, comment: 'On time');
      expect(r.stars, 4);
      expect(r.forwarderId, 'fw_gulf');
      await expectLater(repo.rateForwarder('fr_100', 5), _apiError(409, 'already_rated'));
      await expectLater(repo.rateForwarder('fr_101', 9), _apiError(422, 'validation_error'));
      final created = await repo.createRequest(_requestDraft());
      final cancelled = await repo.closeRequest(created.id);
      expect(cancelled.outcome, 'cancelled');
      await expectLater(repo.rateForwarder(created.id, 5), _apiError(409, 'not_completed'));
    });

    test('create request: screening, validation and exact numbers', () async {
      final repo = fresh();
      final r = await repo.createRequest(_requestDraft());
      expect(r.id, 'fr_1000');
      expect(r.weightKg, '1200.000');
      expect(r.status, 'open');
      expect(r.containerCount, 2);
      expect(r.expiresAt, _clock().add(const Duration(days: 14)));
      await expectLater(
        repo.createRequest(_requestDraft(cargo: 'see http://x.example')),
        _apiError(422, 'content_rejected'),
      );
      await expectLater(
        repo.createRequest(_requestDraft(cargo: 'call 07701234567 now')),
        _apiError(422, 'content_rejected'),
      );
    });

    test('forwarder lifecycle: apply, inbox matching, quote, revise, withdraw, revive', () async {
      final repo = fresh();
      final who0 = await repo.whoami();
      expect(who0.forwarderStatus, isNull);
      await expectLater(repo.inbox(), _apiError(403, 'forwarder_required'));
      await expectLater(
        repo.submitQuote('fr_200', const QuoteDraft(amount: '5', currency: 'USD', transitDays: 3)),
        _apiError(403, 'forwarder_required'),
      );

      const draft = ApplicationDraft(
        companyName: 'Test Freight',
        countryCode: 'CN',
        lanes: [Lane(origin: 'CN', destination: 'IQ')],
        modes: ['sea'],
        incoterms: ['FOB'],
      );
      final app = await repo.apply(draft);
      expect(app.status, 'approved');
      expect((await repo.whoami()).isActive, isTrue);
      await expectLater(repo.apply(draft), _apiError(409, 'already_forwarder'));
      expect((await repo.myApplications()).items.single.id, app.id);

      final inbox = await repo.inbox();
      expect(inbox.items.map((r) => r.id), ['fr_200']);
      expect(inbox.items.single.buyerId, isNull);
      expect(inbox.items.single.hasQuoted, isFalse);
      // a request that does not match the lanes is invisible (404)
      await expectLater(repo.getRequest('fr_201'), _apiError(404, 'not_found'));
      await expectLater(
        repo.submitQuote('fr_201', const QuoteDraft(amount: '5', currency: 'USD', transitDays: 3)),
        _apiError(404, 'not_found'),
      );
      await expectLater(
        repo.submitQuote('fr_100', const QuoteDraft(amount: '5', currency: 'USD', transitDays: 3)),
        _apiError(403, 'own_request'),
      );

      await expectLater(
        repo.submitQuote('fr_200', const QuoteDraft(amount: '5', currency: 'EUR', transitDays: 3)),
        _apiError(422, 'currency_mismatch'),
      );
      await expectLater(
        repo.submitQuote(
          'fr_200',
          const QuoteDraft(
            amount: '100',
            currency: 'USD',
            transitDays: 3,
            breakdown: [QuoteLine(label: 'Ocean', amount: '60'), QuoteLine(label: 'Local', amount: '30')],
          ),
        ),
        _apiError(422, 'breakdown_mismatch'),
      );
      await expectLater(
        repo.submitQuote(
          'fr_200',
          const QuoteDraft(amount: '100', currency: 'USD', transitDays: 3, terms: 'mail me@x.com'),
        ),
        _apiError(422, 'content_rejected'),
      );

      const good = QuoteDraft(
        amount: '100.5',
        currency: 'USD',
        transitDays: 20,
        breakdown: [QuoteLine(label: 'Ocean', amount: '60.50'), QuoteLine(label: 'Local', amount: '40')],
      );
      final q = await repo.submitQuote('fr_200', good);
      expect(q.amount, '100.50');
      expect(q.revision, 1);
      expect(q.breakdown.last.amount, '40.00');
      await expectLater(repo.submitQuote('fr_200', good), _apiError(409, 'quote_exists'));
      expect((await repo.inbox()).items.single.hasQuoted, isTrue);
      expect((await repo.getRequest('fr_200')).quoteCount, 1);

      final revised = await repo.reviseQuote(
        q.id,
        const QuoteDraft(amount: '90', currency: 'USD', transitDays: 18),
      );
      expect(revised.revision, 2);
      expect(revised.amount, '90.00');
      final w = await repo.withdrawQuote(q.id);
      expect(w.status, 'withdrawn');
      expect((await repo.withdrawQuote(q.id)).status, 'withdrawn');
      expect((await repo.getRequest('fr_200')).quoteCount, 0);
      final revived = await repo.reviseQuote(
        q.id,
        const QuoteDraft(amount: '95', currency: 'USD', transitDays: 19),
      );
      expect(revived.status, 'submitted');
      expect(revived.revision, 3);
      expect((await repo.getRequest('fr_200')).quoteCount, 1);

      final mine = await repo.myQuotes();
      expect(mine.items.single.id, q.id);
      expect((await repo.myQuotes(status: 'withdrawn')).items, isEmpty);
      expect((await findMyQuoteForRequest(repo, 'fr_200'))?.id, q.id);
      await expectLater(repo.withdrawQuote('fq_100_1'), _apiError(404, 'not_found'));
    });

    test('manual approval keeps the application pending', () async {
      final repo = fresh(autoApprove: false);
      const draft = ApplicationDraft(
        companyName: 'Test Freight',
        countryCode: 'CN',
        lanes: [Lane(origin: '*', destination: '*')],
        modes: ['sea'],
        incoterms: ['FOB'],
      );
      final app = await repo.apply(draft);
      expect(app.status, 'pending');
      expect((await repo.whoami()).forwarderStatus, isNull);
      await expectLater(repo.apply(draft), _apiError(409, 'application_pending'));
    });

    test('reports are recorded; reporting needs a legitimate relation', () async {
      final repo = fresh();
      await repo.reportQuote('fq_100_1', 'scam_or_fraud');
      await repo.reportRequest('fr_100', 'spam', details: 'x');
      await repo.reportForwarder('fw_silk', 'misleading');
      expect(repo.reports, [
        'quote:fq_100_1:scam_or_fraud',
        'request:fr_100:spam',
        'forwarder:fw_silk:misleading',
      ]);
      await expectLater(repo.reportForwarder('nope', 'spam'), _apiError(404, 'not_found'));
      await expectLater(repo.reportRequest('fr_201', 'spam'), _apiError(404, 'not_found'));
    });

    test('requests expire lazily at expires_at', () async {
      var now = _clock();
      final repo = MockFreightRepository(clock: () => now);
      expect((await repo.getRequest('fr_100')).status, 'open');
      now = now.add(const Duration(days: 13));
      expect((await repo.getRequest('fr_100')).status, 'expired');
      await expectLater(repo.closeRequest('fr_100'), _apiError(409, 'request_expired'));
      await expectLater(repo.acceptQuote('fq_100_1'), _apiError(409, 'request_expired'));
    });
  });

  group('audit regressions', () {
    test('timestamps without a zone are read as UTC', () {
      DateTime? exp(String v) =>
          ShipmentRequest.fromJson({'id': 'x', 'expires_at': v}).expiresAt;
      expect(exp('2026-10-15T10:00:00'), DateTime.utc(2026, 10, 15, 10));
      expect(exp('2026-10-15T10:00:00Z'), DateTime.utc(2026, 10, 15, 10));
      expect(exp('2026-10-15T10:00:00+00:00'), DateTime.utc(2026, 10, 15, 10));
      expect(exp('2026-10-15T13:00:00+03:00'), DateTime.utc(2026, 10, 15, 10));
      expect(exp('2026-10-15T10:00:00.123456'), DateTime.utc(2026, 10, 15, 10, 0, 0, 123, 456));
      expect(exp('garbage'), isNull);
    });

    test('contract-only 409/429 codes have their own message', () {
      for (final code in ['quote_changed', 'rating_too_early', 'rating_pair_limit']) {
        expect(kFreightErrorCodes, contains(code));
        expect(
          freightErrorKey(ApiException(status: 409, code: code, message: code)),
          'freight.err.$code',
        );
      }
    });

    test('weight / volume errors land on the right field', () {
      expect(FreightValidators.weightField('', ''), 'freight.v.weight_or_volume');
      expect(FreightValidators.volumeField('', ''), 'freight.v.weight_or_volume');
      // A bad volume must not flag a valid weight.
      expect(FreightValidators.weightField('10', '1.2345'), isNull);
      expect(FreightValidators.volumeField('10', '1.2345'), 'freight.v.number_scale_3');
      expect(FreightValidators.weightField('0', '5'), 'freight.v.number_scale_3');
      expect(FreightValidators.weightField('١٢٫٥', ''), isNull);
      expect(FreightValidators.volumeField('', '2,5'), isNull);
    });

    test('container count accepts Arabic-Indic digits like the validator', () {
      expect(FreightValidators.intRange('٣', 1, 500, 'k'), isNull);
      expect(int.tryParse(FreightDecimal.normalize('٣') ?? ''), 3);
      expect(FreightValidators.intRange('501', 1, 500, 'k'), 'k');
      expect(FreightValidators.intRange('0', 1, 500, 'k'), 'k');
    });

    test('ready date window is UTC based around midnight', () {
      // 23:30 UTC on 15 Oct: a UTC-5 device is still on 15 Oct, a UTC+3 one is on 16 Oct.
      final now = DateTime.utc(2026, 10, 15, 23, 30);
      expect(FreightValidators.readyDate(DateTime(2026, 10, 15), now), isNull);
      expect(FreightValidators.readyDate(DateTime(2026, 10, 16), now), isNull);
      expect(FreightValidators.readyDate(DateTime(2026, 10, 14), now), 'freight.v.ready_date');
      // 01:00 UTC on 16 Oct: 15 Oct is already yesterday for the server.
      final later = DateTime.utc(2026, 10, 16, 1);
      expect(FreightValidators.readyDate(DateTime(2026, 10, 15), later), 'freight.v.ready_date');
    });

    test('all incoterms and modes in contract are offered', () {
      for (final i in ['EXW', 'FCA', 'FAS', 'FOB', 'CFR', 'CIF', 'CPT', 'CIP', 'DAP', 'DPU', 'DDP']) {
        expect(kFreightIncoterms, contains(i));
      }
      expect(kFreightModes.toSet(), {'sea', 'air', 'road', 'rail'});
    });
  });
}
