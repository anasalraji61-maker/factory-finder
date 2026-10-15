/// Incoterms offered in the checklist (static guidance, offline).
const List<String> kChecklistIncoterms = <String>['EXW', 'FOB', 'CIF', 'DDP'];

const String kDefaultChecklistIncoterm = 'FOB';
const String kDefaultChecklistCountry = 'IQ';

/// One typical import document. [id] is stable (used as the persisted key);
/// i18n keys are 'checklist.doc.<id>' and 'checklist.doc.<id>.hint'.
class ChecklistDoc {
  const ChecklistDoc(this.id, {this.insuranceIncluded = false});

  final String id;

  /// True when the chosen incoterm normally puts insurance on the seller.
  final bool insuranceIncluded;
}

/// Terms under which the seller normally insures the cargo (CIF/CIP/DDP).
const Set<String> _sellerInsures = <String>{'CIF', 'CIP', 'DDP'};

/// Typical documents for [incoterm]. Always guidance, never legal advice.
List<ChecklistDoc> checklistDocsFor(String incoterm) {
  return <ChecklistDoc>[
    const ChecklistDoc('invoice'),
    const ChecklistDoc('packing'),
    const ChecklistDoc('transport'),
    const ChecklistDoc('origin'),
    const ChecklistDoc('conformity'),
    ChecklistDoc('insurance', insuranceIncluded: _sellerInsures.contains(incoterm)),
    const ChecklistDoc('licence'),
  ];
}

/// Storage key for the checked ids of one (country, incoterm) pair.
String checklistStorageKey(String countryCode, String incoterm) =>
    'checklist.v1.${countryCode.toUpperCase()}.${incoterm.toUpperCase()}';

String encodeChecked(Set<String> ids) {
  final sorted = ids.toList()..sort();
  return sorted.join(',');
}

Set<String> decodeChecked(String? raw) {
  if (raw == null || raw.isEmpty) return <String>{};
  return raw.split(',').where((s) => s.isNotEmpty).toSet();
}
