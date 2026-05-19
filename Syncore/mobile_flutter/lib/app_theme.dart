import 'package:flutter/material.dart';

// ── Renk paleti (Kivy versiyonuyla birebir) ────────────────────────────────
class AppColors {
  static const bg       = Color(0xFF0A0A0A);
  static const surface  = Color(0xFF171717);
  static const accent   = Color(0xFF7A2BBF);
  static const accentL  = Color(0xFF9D4EDD);
  static const success  = Color(0xFF10B981);
  static const danger   = Color(0xFFEF4444);
  static const warn     = Color(0xFFF59E0B);
  static const text     = Color(0xFFF3F4F6);
  static const textSub  = Color(0xFFAF99C2);
}

// ── MaterialApp teması ──────────────────────────────────────────────────────
ThemeData buildAppTheme() {
  return ThemeData(
    useMaterial3: true,
    scaffoldBackgroundColor: AppColors.bg,
    colorScheme: const ColorScheme.dark(
      surface:   AppColors.surface,
      primary:   AppColors.accent,
      secondary: AppColors.accentL,
      error:     AppColors.danger,
    ),
    appBarTheme: const AppBarTheme(
      backgroundColor: AppColors.bg,
      foregroundColor: AppColors.text,
      elevation: 0,
    ),
    textTheme: const TextTheme(
      bodyLarge:   TextStyle(color: AppColors.text),
      bodyMedium:  TextStyle(color: AppColors.text),
      bodySmall:   TextStyle(color: AppColors.textSub),
      titleLarge:  TextStyle(color: AppColors.text, fontWeight: FontWeight.bold),
      titleMedium: TextStyle(color: AppColors.text),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: const Color(0xFF1E1229),
      hintStyle: const TextStyle(color: AppColors.textSub),
      labelStyle: const TextStyle(color: AppColors.textSub),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: Color(0xFF3D1F5E), width: 1),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: const BorderSide(color: AppColors.accentL, width: 2),
      ),
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        backgroundColor: AppColors.accent,
        foregroundColor: AppColors.text,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
        padding: const EdgeInsets.symmetric(vertical: 14),
        textStyle: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
      ),
    ),
  );
}
