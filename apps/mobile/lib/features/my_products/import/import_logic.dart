import 'package:factory_finder/core/models/models.dart';
import 'package:factory_finder/features/my_products/import/import_models.dart';
import 'package:factory_finder/features/my_products/my_products_logic.dart';
import 'package:factory_finder/features/my_products/my_products_models.dart';

/// Server limit of items per import request.
const int kImportBatchSize = 100;

/// Client-side cap on pasted data rows (keeps the screen responsive).
const int kImportMaxRows = 1000;

/// Columns that must be present in the header row.
const List<String> kImportRequiredColumns = <String>[
  'external_ref',
  'title',
  'category',
  'price_min',
  'country',
];

final RegExp _refPattern = RegExp(r'^[A-Za-z0-9][A-Za-z0-9_.:\-/]{0,63}$');
final RegExp _currencyPattern = RegExp(r'^[A-Z]{3}$');
final RegExp _countryPattern = RegExp(r'^[A-Z]{2}$');
final RegExp _headerSeparators = RegExp(r'[\s\-]+');
final RegExp _imageSeparators = RegExp(r'[|\s]+');

/// Picks the delimiter from the header line: comma, else tab (spreadsheet
/// paste), else semicolon, else comma.
String detectCsvDelimiter(String text) {
  var end = text.indexOf('\n');
  if (end < 0) end = text.length;
  final first = text.substring(0, end);
  if (first.contains(',')) return ',';
  if (first.contains('\t')) return '\t';
  if (first.contains(';')) return ';';
  return ',';
}

/// Minimal RFC 4180 parser: quoted fields, `""` escapes, commas and newlines
/// inside quotes, CRLF / LF / CR record ends, a leading UTF-8 BOM, and a final
/// record without a trailing newline. Throws [FormatException] on an
/// unterminated quote. Blank lines come back as `['']`.
List<List<String>> parseCsv(String input, {String? delimiter}) {
  var text = input;
  if (text.isNotEmpty && text.codeUnitAt(0) == 0xFEFF) text = text.substring(1);
  final d = delimiter ?? detectCsvDelimiter(text);
  final rows = <List<String>>[];
  var row = <String>[];
  final field = StringBuffer();
  var inQuotes = false;
  var i = 0;
  final n = text.length;
  while (i < n) {
    final c = text[i];
    if (inQuotes) {
      if (c == '"') {
        if (i + 1 < n && text[i + 1] == '"') {
          field.write('"');
          i += 2;
          continue;
        }
        inQuotes = false;
        i++;
        continue;
      }
      field.write(c);
      i++;
      continue;
    }
    if (c == '"' && field.isEmpty) {
      inQuotes = true;
      i++;
      continue;
    }
    if (c == d) {
      row.add(field.toString());
      field.clear();
      i++;
      continue;
    }
    if (c == '\r' || c == '\n') {
      if (c == '\r' && i + 1 < n && text[i + 1] == '\n') i++;
      row.add(field.toString());
      field.clear();
      rows.add(row);
      row = <String>[];
      i++;
      continue;
    }
    field.write(c);
    i++;
  }
  if (inQuotes) throw const FormatException('Unterminated quoted field');
  if (field.isNotEmpty || row.isNotEmpty) {
    row.add(field.toString());
    rows.add(row);
  }
  return rows;
}

/// A problem with one CSV cell: the column name and an i18n key.
class ImportRowError {
  const ImportRowError(this.column, this.key);
  final String column;
  final String key;
}

/// One parsed data row. [body] is the ready `ListingImportItem` JSON when the
/// row is valid.
class ImportRow {
  const ImportRow({
    required this.rowNumber,
    required this.externalRef,
    required this.title,
    this.body,
    this.errors = const <ImportRowError>[],
  });

  /// 1-based row in the pasted text (the header is row 1).
  final int rowNumber;
  final String externalRef;
  final String title;
  final Map<String, dynamic>? body;
  final List<ImportRowError> errors;

  bool get isValid => body != null && errors.isEmpty;
}

/// Result of parsing the pasted text. [errorKey] is set when nothing can be
/// imported at all (empty text, bad quoting, missing columns, too many rows).
class ImportParseResult {
  const ImportParseResult({
    this.rows = const <ImportRow>[],
    this.errorKey,
    this.missingColumns = const <String>[],
  });

  final List<ImportRow> rows;
  final String? errorKey;
  final List<String> missingColumns;

  List<ImportRow> get validRows => rows.where((r) => r.isValid).toList();
  List<ImportRow> get invalidRows => rows.where((r) => !r.isValid).toList();
  int get batchCount => (validRows.length + kImportBatchSize - 1) ~/ kImportBatchSize;
}

String _normalizeHeader(String h) =>
    h.trim().toLowerCase().replaceAll(_headerSeparators, '_');

bool _blank(List<String> r) => r.every((c) => c.trim().isEmpty);

ListingKind? _kindOf(String s) {
  final t = s.trim().toLowerCase().replaceAll(_headerSeparators, '_');
  for (final v in ListingKind.values) {
    if (v.json == t) return v;
  }
  return null;
}

ItemCondition? _conditionOf(String s) {
  final t = s.trim().toLowerCase().replaceAll(_headerSeparators, '_');
  if (t == 'brand_new') return ItemCondition.brandNew;
  for (final v in ItemCondition.values) {
    if (v.json == t) return v;
  }
  return null;
}

Incoterm? _incotermOf(String s) {
  final t = s.trim().toUpperCase();
  for (final v in Incoterm.values) {
    if (v.json == t) return v;
  }
  return null;
}

const Map<String, List<String>> _draftFieldColumns = <String, List<String>>{
  'title': ['title'],
  'titleAr': ['title_ar'],
  'description': ['description'],
  'descriptionAr': ['description_ar'],
  'category': ['category'],
  'priceMin': ['price_min'],
  'priceMax': ['price_max'],
  'moq': ['moq'],
  'unit': ['unit'],
  'weight': ['unit_weight_kg'],
  'volume': ['unit_volume_m3'],
  'hs': ['hs_code'],
  'lead': ['lead_time_min', 'lead_time_max'],
  'images': ['images'],
};

/// Parses and validates pasted CSV into import rows. Never throws.
///
/// Supported columns (header names are case-insensitive): external_ref,
/// title, category, price_min, country (required); title_ar, description,
/// description_ar, price_max (defaults to price_min), currency (USD), unit
/// (piece), moq (1), kind (product), condition (new), incoterm,
/// unit_weight_kg, unit_volume_m3, hs_code, lead_time_min, lead_time_max,
/// images (URLs separated by `|`), city.
ImportParseResult parseListingCsv(String text) {
  List<List<String>> records;
  try {
    records = parseCsv(text);
  } on FormatException {
    return const ImportParseResult(errorKey: 'myp.imp.err.quote');
  }
  var headerAt = -1;
  for (var i = 0; i < records.length; i++) {
    if (!_blank(records[i])) {
      headerAt = i;
      break;
    }
  }
  if (headerAt < 0) return const ImportParseResult(errorKey: 'myp.imp.err.empty');

  final index = <String, int>{};
  final header = records[headerAt];
  for (var c = 0; c < header.length; c++) {
    var name = _normalizeHeader(header[c]);
    if (name == 'country_code') name = 'country';
    if (name.isNotEmpty && !index.containsKey(name)) index[name] = c;
  }
  final missing = <String>[
    for (final col in kImportRequiredColumns)
      if (!index.containsKey(col)) col,
  ];
  if (missing.isNotEmpty) {
    return ImportParseResult(errorKey: 'myp.imp.err.columns', missingColumns: missing);
  }

  final rows = <ImportRow>[];
  final seenRefs = <String>{};
  for (var r = headerAt + 1; r < records.length; r++) {
    final rec = records[r];
    if (_blank(rec)) continue;
    if (rows.length >= kImportMaxRows) {
      return const ImportParseResult(errorKey: 'myp.imp.err.too_many');
    }
    rows.add(_parseRow(r + 1, rec, index, seenRefs));
  }
  if (rows.isEmpty) return const ImportParseResult(errorKey: 'myp.imp.err.no_rows');
  return ImportParseResult(rows: rows);
}

ImportRow _parseRow(
  int rowNumber,
  List<String> rec,
  Map<String, int> index,
  Set<String> seenRefs,
) {
  String cell(String name) {
    final at = index[name];
    if (at == null || at >= rec.length) return '';
    return rec[at].trim();
  }

  final errors = <ImportRowError>[];
  void err(String column, String key) => errors.add(ImportRowError(column, key));

  final ref = cell('external_ref');
  if (!_refPattern.hasMatch(ref)) {
    err('external_ref', 'myp.imp.err.ref_invalid');
  } else if (!seenRefs.add(ref)) {
    err('external_ref', 'myp.imp.err.ref_duplicate');
  }

  var kind = ListingKind.product;
  final kindText = cell('kind');
  if (kindText.isNotEmpty) {
    final k = _kindOf(kindText);
    if (k == null) {
      err('kind', 'myp.imp.err.kind');
    } else {
      kind = k;
    }
  }

  var condition = ItemCondition.brandNew;
  final condText = cell('condition');
  if (condText.isNotEmpty) {
    final c = _conditionOf(condText);
    if (c == null) {
      err('condition', 'myp.imp.err.condition');
    } else {
      condition = c;
    }
  }

  Incoterm? incoterm;
  final incText = cell('incoterm');
  if (incText.isNotEmpty) {
    incoterm = _incotermOf(incText);
    if (incoterm == null) err('incoterm', 'myp.imp.err.incoterm');
  }

  var currency = cell('currency').toUpperCase();
  if (currency.isEmpty) currency = 'USD';
  if (!_currencyPattern.hasMatch(currency)) err('currency', 'myp.imp.err.currency');

  final country = cell('country').toUpperCase();
  if (!_countryPattern.hasMatch(country)) err('country', 'myp.imp.err.country');

  final priceMin = cell('price_min');
  var priceMax = cell('price_max');
  if (priceMax.isEmpty) priceMax = priceMin;
  final moq = cell('moq');
  final unit = cell('unit');
  final imagesText = cell('images');
  final images = imagesText.isEmpty
      ? const <String>[]
      : imagesText.split(_imageSeparators).where((u) => u.isNotEmpty).toList();

  final draft = ProductDraft(
    kind: kind,
    condition: condition,
    title: cell('title'),
    titleAr: cell('title_ar'),
    description: cell('description'),
    descriptionAr: cell('description_ar'),
    category: cell('category'),
    priceMin: priceMin,
    priceMax: priceMax,
    currency: currency,
    unit: unit.isEmpty ? 'piece' : unit,
    moq: moq.isEmpty ? '1' : moq,
    incoterm: incoterm,
    unitWeightKg: cell('unit_weight_kg'),
    unitVolumeM3: cell('unit_volume_m3'),
    hsCode: cell('hs_code'),
    leadMin: cell('lead_time_min'),
    leadMax: cell('lead_time_max'),
    images: images,
    origin: Location(
      countryCode: country,
      city: cell('city').isEmpty ? null : cell('city'),
    ),
  );
  final draftErrors = validateProductDraft(draft);
  draftErrors.forEach((field, key) {
    final cols = _draftFieldColumns[field];
    err(cols == null ? field : cols.join('/'), key);
  });

  if (errors.isNotEmpty) {
    return ImportRow(
      rowNumber: rowNumber,
      externalRef: ref,
      title: draft.title,
      errors: errors,
    );
  }
  return ImportRow(
    rowNumber: rowNumber,
    externalRef: ref,
    title: draft.title,
    body: <String, dynamic>{
      ...buildListingBody(draft),
      'external_ref': ref,
    },
  );
}

/// Splits [items] into consecutive chunks of at most [size].
List<List<T>> chunkItems<T>(List<T> items, [int size = kImportBatchSize]) {
  final out = <List<T>>[];
  for (var i = 0; i < items.length; i += size) {
    final end = i + size > items.length ? items.length : i + size;
    out.add(items.sublist(i, end));
  }
  return out;
}

/// What happened to one pasted row. [action] is `created`, `updated`,
/// `rejected` (server) or `invalid` (failed client validation, never sent).
class ImportOutcome {
  const ImportOutcome({
    required this.rowNumber,
    required this.externalRef,
    required this.title,
    required this.action,
    this.reason,
    this.message,
    this.errors = const <ImportRowError>[],
  });

  final int rowNumber;
  final String externalRef;
  final String title;
  final String action;
  final String? reason;
  final String? message;
  final List<ImportRowError> errors;
}

/// Client-invalid rows as outcomes (shown live, before anything is sent).
List<ImportOutcome> invalidOutcomes(List<ImportRow> rows) => <ImportOutcome>[
      for (final r in rows)
        if (!r.isValid)
          ImportOutcome(
            rowNumber: r.rowNumber,
            externalRef: r.externalRef,
            title: r.title,
            action: 'invalid',
            errors: r.errors,
          ),
    ];

/// Aggregate of a (possibly partial) import run.
class ImportRunResult {
  const ImportRunResult({
    required this.dryRun,
    required this.outcomes,
    required this.batches,
    required this.batchesDone,
    this.error,
  });

  final bool dryRun;
  final List<ImportOutcome> outcomes;
  final int batches;
  final int batchesDone;

  /// Set when a batch failed; earlier batches' outcomes are kept.
  final Object? error;

  int count(String action) => outcomes.where((o) => o.action == action).length;
  int get created => count('created');
  int get updated => count('updated');
  int get rejected => count('rejected');
  int get invalid => count('invalid');
  bool get complete => error == null && batchesDone == batches;
}

typedef ImportSender = Future<ImportResponse> Function(
  List<Map<String, dynamic>> items,
  bool dryRun,
);

/// Sends the valid rows of [rows] in chunks of [kImportBatchSize] through
/// [send] and merges the per-item results back onto the original rows.
/// Stops at the first failing batch and reports it in [ImportRunResult.error].
Future<ImportRunResult> runImportBatches(
  List<ImportRow> rows,
  ImportSender send, {
  required bool dryRun,
  void Function(int done, int total)? onProgress,
}) async {
  final valid = rows.where((r) => r.isValid).toList();
  final chunks = chunkItems<ImportRow>(valid);
  final byRow = <int, ImportOutcome>{};
  var done = 0;
  Object? failure;
  for (final chunk in chunks) {
    try {
      final resp = await send(
        <Map<String, dynamic>>[for (final r in chunk) r.body!],
        dryRun,
      );
      for (var k = 0; k < chunk.length; k++) {
        // A row the server did not answer for must not vanish silently.
        final r = chunk[k];
        byRow[r.rowNumber] = ImportOutcome(
          rowNumber: r.rowNumber,
          externalRef: r.externalRef,
          title: r.title,
          action: 'rejected',
          reason: 'missing_result',
        );
      }
      for (final res in resp.results) {
        if (res.index < 0 || res.index >= chunk.length) continue;
        final row = chunk[res.index];
        byRow[row.rowNumber] = ImportOutcome(
          rowNumber: row.rowNumber,
          externalRef: row.externalRef,
          title: row.title,
          action: res.action,
          reason: res.reason,
          message: res.message,
        );
      }
    } catch (e) {
      failure = e;
      break;
    }
    done++;
    if (onProgress != null) onProgress(done, chunks.length);
  }
  final outcomes = <ImportOutcome>[];
  for (final r in rows) {
    if (!r.isValid) {
      outcomes.add(ImportOutcome(
        rowNumber: r.rowNumber,
        externalRef: r.externalRef,
        title: r.title,
        action: 'invalid',
        errors: r.errors,
      ));
    } else {
      final o = byRow[r.rowNumber];
      if (o != null) outcomes.add(o);
    }
  }
  return ImportRunResult(
    dryRun: dryRun,
    outcomes: outcomes,
    batches: chunks.length,
    batchesDone: done,
    error: failure,
  );
}
