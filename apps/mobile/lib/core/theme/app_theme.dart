import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

class AppColors {
  AppColors._();
  static const Color primary = Color(0xFF2340D9);
  static const Color primaryDark = Color(0xFF16288F);
  static const Color accent = Color(0xFF00BFA6);
  static const Color success = Color(0xFF16A34A);
  static const Color warning = Color(0xFFF59E0B);
  static const Color danger = Color(0xFFDC2626);
  static const Color surface = Color(0xFFFFFFFF);
  static const Color background = Color(0xFFF4F6FB);
  static const Color textPrimary = Color(0xFF0F172A);
  static const Color textSecondary = Color(0xFF566478); // >= 4.5:1 on light surfaces
  /// Secondary text colour on dark surfaces (>= 7:1 on [AppTheme.darkSurface]).
  static const Color textSecondaryDark = Color(0xFFA3AEC6);

  /// Theme-aware secondary text colour. Prefer this over [textSecondary]
  /// wherever the widget can be shown on the dark theme.
  static Color secondaryOf(BuildContext context) =>
      Theme.of(context).brightness == Brightness.dark
          ? textSecondaryDark
          : textSecondary;
  static const Color border = Color(0xFFE2E8F0);
}

class AppSpacing {
  AppSpacing._();
  static const double xs = 4, sm = 8, md = 12, lg = 16, xl = 24, xxl = 32;
}

class AppRadius {
  AppRadius._();
  static const double sm = 8, md = 14, lg = 20, xl = 28;
}

class AppTheme {
  AppTheme._();

  static const Color darkBackground = Color(0xFF0B1020);
  static const Color darkSurface = Color(0xFF141B31);

  static ThemeData light() => _build(Brightness.light);
  static ThemeData dark() => _build(Brightness.dark);

  static TextTheme _textTheme(TextTheme base) {
    try {
      return GoogleFonts.cairoTextTheme(base);
    } catch (_) {
      return base; // graceful fallback to the platform font
    }
  }

  static ThemeData _build(Brightness brightness) {
    final isDark = brightness == Brightness.dark;
    final bg = isDark ? darkBackground : AppColors.background;
    final surface = isDark ? darkSurface : AppColors.surface;
    final scheme = ColorScheme.fromSeed(
      seedColor: AppColors.primary,
      brightness: brightness,
    ).copyWith(
      primary: isDark ? const Color(0xFF8EA2FF) : AppColors.primary,
      onPrimary: isDark ? darkBackground : Colors.white,
      secondary: AppColors.accent,
      onSecondary: const Color(0xFF04120F),
      error: isDark ? const Color(0xFFFF8A80) : AppColors.danger,
      onError: isDark ? const Color(0xFF1A0505) : Colors.white,
      surface: surface,
      onSurface: isDark ? const Color(0xFFE6E9F5) : AppColors.textPrimary,
      onSurfaceVariant: isDark ? AppColors.textSecondaryDark : AppColors.textSecondary,
      outline: isDark ? const Color(0xFF8B96B5) : const Color(0xFF7A8699),
    );
    final base = ThemeData(
      useMaterial3: true,
      brightness: brightness,
      colorScheme: scheme,
      scaffoldBackgroundColor: bg,
    );
    return base.copyWith(
      textTheme: _textTheme(base.textTheme),
      appBarTheme: AppBarTheme(
        backgroundColor: bg,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        scrolledUnderElevation: 0,
        centerTitle: false,
        foregroundColor: isDark ? Colors.white : AppColors.textPrimary,
      ),
      navigationBarTheme: NavigationBarThemeData(
        backgroundColor: surface,
        surfaceTintColor: Colors.transparent,
        indicatorColor: scheme.primary.withOpacity(isDark ? 0.30 : 0.12),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: surface,
        contentPadding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.lg,
          vertical: AppSpacing.md,
        ),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppRadius.md),
          borderSide: BorderSide(
            color: isDark ? const Color(0xFF26304D) : AppColors.border,
          ),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppRadius.md),
          borderSide: BorderSide(
            color: isDark ? const Color(0xFF26304D) : AppColors.border,
          ),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppRadius.md),
          borderSide: BorderSide(color: scheme.primary, width: 1.5),
        ),
        hintStyle: TextStyle(
          color: isDark ? AppColors.textSecondaryDark : AppColors.textSecondary,
        ),
      ),
    );
  }
}
