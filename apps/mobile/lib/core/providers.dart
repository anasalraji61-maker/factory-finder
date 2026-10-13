import 'package:factory_finder/core/models/models.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

final localeProvider = StateProvider<Locale>((ref) => const Locale('ar'));
final themeModeProvider = StateProvider<ThemeMode>((ref) => ThemeMode.light);
final displayCurrencyProvider = StateProvider<String>((ref) => 'USD');
final destinationProvider = StateProvider<Location?>(
  (ref) => const Location(countryCode: 'IQ', city: 'Baghdad'),
);
