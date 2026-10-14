import 'package:factory_finder/core/models/models.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

final localeProvider = StateProvider<Locale>((ref) => const Locale('ar'));
final themeModeProvider = StateProvider<ThemeMode>((ref) => ThemeMode.system);

/// Default display currency matches the default destination (Iraq -> IQD).
final displayCurrencyProvider = StateProvider<String>((ref) => 'IQD');

/// Digit style used for numbers shown to the user (see `core/utils/digits.dart`).
enum DigitStyle { western, arabicIndic }

final digitStyleProvider =
    StateProvider<DigitStyle>((ref) => DigitStyle.western);
final destinationProvider = StateProvider<Location?>(
  (ref) => const Location(countryCode: 'IQ', city: 'Baghdad'),
);
