import 'package:factory_finder/app.dart';
import 'package:factory_finder/core/router/app_router.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  registerFeatureStrings();
  runApp(const ProviderScope(child: FactoryFinderApp()));
}
