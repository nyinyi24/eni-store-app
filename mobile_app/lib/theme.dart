import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

class AppColors {
  static const bg = Color(0xFF0B1220);
  static const surface = Color(0xFF131C2E);
  static const surfaceHi = Color(0xFF1B2740);
  static const border = Color(0xFF24324D);
  static const primary = Color(0xFF14B8A6);
  static const accent = Color(0xFF38BDF8);
  static const warn = Color(0xFFF59E0B);
  static const danger = Color(0xFFEF4444);
  static const ok = Color(0xFF22C55E);
  static const textDim = Color(0xFF94A3B8);
}

ThemeData buildAppTheme() {
  return ThemeData(
    brightness: Brightness.dark,
    useMaterial3: true,
    scaffoldBackgroundColor: AppColors.bg,
    primaryColor: AppColors.primary,
    colorScheme: const ColorScheme.dark(
      primary: AppColors.primary,
      secondary: AppColors.accent,
      surface: AppColors.surface,
    ),
    appBarTheme: const AppBarTheme(
      backgroundColor: AppColors.bg,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      centerTitle: false,
      titleTextStyle: TextStyle(fontSize: 20, fontWeight: FontWeight.w800, color: Colors.white),
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: AppColors.surface,
      indicatorColor: AppColors.primary.withAlpha(60),
      labelTextStyle: WidgetStateProperty.all(
        const TextStyle(fontSize: 12, fontWeight: FontWeight.w600),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: AppColors.surface,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(14),
        borderSide: const BorderSide(color: AppColors.border),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(14),
        borderSide: const BorderSide(color: AppColors.border),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(14),
        borderSide: const BorderSide(color: AppColors.primary, width: 1.6),
      ),
    ),
    snackBarTheme: SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
    ),
  );
}

/// 10000.0 -> "10,000"
String fmtMoney(dynamic v) {
  final n = (v is num) ? v : (num.tryParse('$v') ?? 0);
  final s = n.round().toString();
  final buf = StringBuffer();
  for (int i = 0; i < s.length; i++) {
    final fromEnd = s.length - i;
    buf.write(s[i]);
    if (fromEnd > 1 && fromEnd % 3 == 1 && s[i] != '-') buf.write(',');
  }
  return buf.toString();
}

class StoreCategory {
  final String id;
  final String label;
  final IconData icon;
  final Color color;
  final List<String> keywords;
  const StoreCategory(this.id, this.label, this.icon, this.color, this.keywords);
}

const StoreCategory kAll =
    StoreCategory('all', 'All', Icons.apps_rounded, AppColors.primary, []);

const List<StoreCategory> kCategories = [
  StoreCategory('telegram', 'Telegram', Icons.send_rounded, Color(0xFF38BDF8), ['telegram']),
  StoreCategory('gift', 'Gift Cards', Icons.card_giftcard_rounded, Color(0xFFF472B6), ['gift card']),
  StoreCategory('ai', 'AI Tools', Icons.auto_awesome_rounded, Color(0xFFA78BFA),
      ['gemini', 'chat gpt', 'chatgpt', 'claude', 'grok', 'perplexity', 'cursor', 'copilot']),
  StoreCategory('vpn', 'VPN', Icons.shield_rounded, Color(0xFF34D399), ['vpn', 'outline']),
  StoreCategory('stream', 'Streaming', Icons.play_circle_rounded, Color(0xFFF87171),
      ['netflix', 'disney', 'hbo', 'prime video', 'iqiyi', 'crunchyroll', 'youtube', 'spotify', 'apple music']),
  StoreCategory('tools', 'Apps & Tools', Icons.widgets_rounded, Color(0xFFFBBF24), [
    'capcut', 'canva', 'adobe', 'picsart', 'alight', 'meitu', 'wink', 'freepik', 'notion',
    'zoom', 'grammarly', 'microsoft', 'coursera', 'duolingo', 'linkedin', 'tradingview'
  ]),
];

const StoreCategory kOther =
    StoreCategory('other', 'Others', Icons.category_rounded, Color(0xFF94A3B8), []);

StoreCategory categoryOf(String name) {
  final n = name.toLowerCase();
  for (final c in kCategories) {
    for (final k in c.keywords) {
      if (n.contains(k)) return c;
    }
  }
  return kOther;
}

IconData iconForProduct(String name) {
  final n = name.toLowerCase();
  if (n.contains('premium') && n.contains('telegram')) return Icons.workspace_premium_rounded;
  if (n.contains('stars')) return Icons.star_rounded;
  if (n.contains('telegram')) return Icons.send_rounded;
  if (n.contains('gift card')) return Icons.card_giftcard_rounded;
  if (n.contains('gemini') || n.contains('grok') || n.contains('perplexity')) return Icons.auto_awesome_rounded;
  if (n.contains('chat gpt') || n.contains('chatgpt') || n.contains('claude')) return Icons.smart_toy_rounded;
  if (n.contains('cursor')) return Icons.code_rounded;
  if (n.contains('vpn') || n.contains('outline')) return Icons.vpn_key_rounded;
  if (n.contains('spotify') || n.contains('apple music')) return Icons.music_note_rounded;
  if (n.contains('netflix') || n.contains('disney') || n.contains('hbo') ||
      n.contains('prime') || n.contains('iqiyi') || n.contains('crunchyroll') || n.contains('youtube')) {
    return Icons.movie_rounded;
  }
  if (n.contains('capcut') || n.contains('alight') || n.contains('wink')) return Icons.videocam_rounded;
  if (n.contains('canva') || n.contains('picsart') || n.contains('meitu') || n.contains('freepik') || n.contains('adobe')) {
    return Icons.palette_rounded;
  }
  if (n.contains('microsoft') || n.contains('notion') || n.contains('zoom') || n.contains('grammarly')) {
    return Icons.work_rounded;
  }
  if (n.contains('coursera') || n.contains('duolingo')) return Icons.school_rounded;
  if (n.contains('linkedin')) return Icons.badge_rounded;
  if (n.contains('tradingview')) return Icons.show_chart_rounded;
  if (n.contains('mail')) return Icons.mail_rounded;
  if (n.contains('tiktok')) return Icons.trending_up_rounded;
  return categoryOf(name).icon;
}

Color colorForProduct(String name) => categoryOf(name).color;

/// Open the shop's Telegram contact directly in the Telegram app (falls back to browser).
Future<bool> openTelegramSupport(String? supportUrl) async {
  final url = (supportUrl == null || supportUrl.trim().isEmpty)
      ? 'https://t.me/independence_N'
      : supportUrl.trim();
  final uri = Uri.parse(url);
  if (uri.host == 't.me' && uri.pathSegments.isNotEmpty) {
    final tg = Uri.parse('tg://resolve?domain=${uri.pathSegments.first}');
    try {
      if (await launchUrl(tg, mode: LaunchMode.externalApplication)) return true;
    } catch (_) {}
  }
  try {
    return await launchUrl(uri, mode: LaunchMode.externalApplication);
  } catch (_) {
    return false;
  }
}

class IconTile extends StatelessWidget {
  final IconData icon;
  final Color color;
  final double size;
  const IconTile({super.key, required this.icon, required this.color, this.size = 46});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(size * 0.32),
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [color.withAlpha(70), color.withAlpha(25)],
        ),
        border: Border.all(color: color.withAlpha(90)),
      ),
      child: Icon(icon, color: color, size: size * 0.52),
    );
  }
}

class SectionCard extends StatelessWidget {
  final Widget child;
  final EdgeInsets padding;
  const SectionCard({super.key, required this.child, this.padding = const EdgeInsets.all(16)});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: padding,
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: AppColors.border),
      ),
      child: child,
    );
  }
}
