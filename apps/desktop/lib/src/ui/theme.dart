import 'package:flutter/material.dart';

/// Токены оформления из `web/tokens.json` / `web/css/tokens.css`.
class IltPalette {
  const IltPalette({
    required this.bgScene,
    required this.bgPrimary,
    required this.bgSecondary,
    required this.surface1,
    required this.surface2,
    required this.surface3,
    required this.line,
    required this.lineSoft,
    required this.primary,
    required this.primaryHover,
    required this.primaryFg,
    required this.accent,
    required this.border,
    required this.borderStrong,
    required this.input,
    required this.textPrimary,
    required this.textMuted,
    required this.textSuccess,
    required this.textWarning,
    required this.textError,
  });

  final Color bgScene;
  final Color bgPrimary;
  final Color bgSecondary;
  final Color surface1;
  final Color surface2;
  final Color surface3;
  final Color line;
  final Color lineSoft;
  final Color primary;
  final Color primaryHover;
  final Color primaryFg;
  final Color accent;
  final Color border;
  final Color borderStrong;
  final Color input;
  final Color textPrimary;
  final Color textMuted;
  final Color textSuccess;
  final Color textWarning;
  final Color textError;

  static const dark = IltPalette(
    bgScene: Color(0xFF08090D),
    bgPrimary: Color(0xFF0F1115),
    bgSecondary: Color(0xFF0B0C10),
    surface1: Color(0xFF141822),
    surface2: Color(0xFF1B2230),
    surface3: Color(0xFF232C3F),
    line: Color(0xFF232B3A),
    lineSoft: Color(0xFF1A202C),
    primary: Color(0xFF3890B5),
    primaryHover: Color(0xFF0F92E6),
    primaryFg: Color(0xFF0B0C10),
    accent: Color(0xFF2F3542),
    border: Color(0xFF202A38),
    borderStrong: Color(0xFF6B7689),
    input: Color(0xFF101216),
    textPrimary: Color(0xFFE6EEF8),
    textMuted: Color(0xFF9AA3BF),
    textSuccess: Color(0xFF7BD389),
    textWarning: Color(0xFFF0C674),
    textError: Color(0xFFFF7B95),
  );

  static const light = IltPalette(
    bgScene: Color(0xFFE2E5EA),
    bgPrimary: Color(0xFFF0F2F5),
    bgSecondary: Color(0xFFE4E6EB),
    surface1: Color(0xFFF6F7F9),
    surface2: Color(0xFFFFFFFF),
    surface3: Color(0xFFFFFFFF),
    line: Color(0xFFDADDE4),
    lineSoft: Color(0xFFE7E9EF),
    primary: Color(0xFF0B6FB0),
    primaryHover: Color(0xFF0878C7),
    primaryFg: Color(0xFFFFFFFF),
    accent: Color(0xFFE4E6EB),
    border: Color(0xFFD0D3D9),
    borderStrong: Color(0xFF5C6370),
    input: Color(0xFFFFFFFF),
    textPrimary: Color(0xFF1A1D21),
    textMuted: Color(0xFF5C6370),
    textSuccess: Color(0xFF2E7D32),
    textWarning: Color(0xFF8A6500),
    textError: Color(0xFFC62828),
  );

  static IltPalette of(BuildContext context) =>
      Theme.of(context).brightness == Brightness.dark ? dark : light;
}

/// Единая высота однострочных полей (поиск, инспектор, настройки) — 028.
const double kFieldHeight = 32;

/// Метрики chrome, растущие вместе с масштабом интерфейса (токены web).
class ChromeMetrics {
  const ChromeMetrics({
    required this.appBarHeight,
    required this.railWidth,
    required this.inspectorWidth,
    required this.statusBarHeight,
    required this.dockHeight,
    required this.fontSize,
  });

  factory ChromeMetrics.scaled(double scale) => ChromeMetrics(
        appBarHeight: 46 * scale,
        railWidth: 268 * scale,
        inspectorWidth: 344 * scale,
        statusBarHeight: 28 * scale,
        dockHeight: 52 * scale,
        fontSize: 13 * scale,
      );

  final double appBarHeight;
  final double railWidth;
  final double inspectorWidth;
  final double statusBarHeight;
  final double dockHeight;
  final double fontSize;
}

/// Тема хоста: dark / light / system по настройкам bootstrap.
ThemeData buildIltTheme({
  required String themeName,
  required double scale,
  Brightness platform = Brightness.dark,
}) {
  var dark = true;
  if (themeName == 'light') {
    dark = false;
  } else if (themeName != 'dark') {
    dark = platform == Brightness.dark;
  }
  final c = dark ? IltPalette.dark : IltPalette.light;
  final scheme = ColorScheme(
    brightness: dark ? Brightness.dark : Brightness.light,
    primary: c.primary,
    onPrimary: c.primaryFg,
    secondary: c.primaryHover,
    onSecondary: Colors.white,
    error: c.textError,
    onError: Colors.white,
    surface: c.bgPrimary,
    onSurface: c.textPrimary,
    surfaceContainerLowest: c.bgScene,
    surfaceContainerLow: c.bgSecondary,
    surfaceContainer: c.surface1,
    surfaceContainerHigh: c.surface2,
    surfaceContainerHighest: c.surface3,
    onSurfaceVariant: c.textMuted,
    outline: c.border,
    outlineVariant: c.line,
    surfaceTint: Colors.transparent,
  );
  final base = ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: c.bgPrimary,
  );
  return base.copyWith(
    textTheme: base.textTheme.copyWith(
      bodyLarge: TextStyle(fontSize: 14 * scale, color: c.textPrimary),
      bodyMedium: TextStyle(fontSize: 13 * scale, color: c.textPrimary),
      bodySmall: TextStyle(fontSize: 12 * scale, color: c.textMuted),
      labelSmall: TextStyle(fontSize: 11 * scale, color: c.textMuted),
      labelMedium: TextStyle(fontSize: 12 * scale, color: c.textPrimary),
      titleSmall: TextStyle(
        fontSize: 14 * scale,
        color: c.textPrimary,
        fontWeight: FontWeight.w600,
      ),
    ),
    dividerTheme: DividerThemeData(color: c.line, thickness: 1, space: 1),
    iconTheme: IconThemeData(color: c.textMuted, size: 16 * scale),
    progressIndicatorTheme: ProgressIndicatorThemeData(
      color: c.primary,
      linearMinHeight: 3 * scale,
    ),
    tooltipTheme: TooltipThemeData(
      waitDuration: const Duration(milliseconds: 500),
      textStyle: TextStyle(fontSize: 11 * scale, color: c.bgPrimary),
      decoration: BoxDecoration(
        color: c.textPrimary,
        borderRadius: BorderRadius.circular(4),
      ),
    ),
  );
}
