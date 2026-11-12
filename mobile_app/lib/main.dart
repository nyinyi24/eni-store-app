import 'package:flutter/material.dart';
import 'api_service.dart';
import 'screens/auth_screen.dart';
import 'screens/shop_screen.dart';
import 'screens/orders_screen.dart';
import 'screens/wallet_screen.dart';
import 'screens/profile_screen.dart';
import 'theme.dart';

void main() {
  runApp(const EniStoreApp());
}

class EniStoreApp extends StatelessWidget {
  const EniStoreApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'ENI Premium Store',
      debugShowCheckedModeBanner: false,
      theme: buildAppTheme(),
      home: const RootWrapper(),
    );
  }
}

class RootWrapper extends StatefulWidget {
  const RootWrapper({super.key});

  @override
  State<RootWrapper> createState() => _RootWrapperState();
}

class _RootWrapperState extends State<RootWrapper> {
  bool? isAuthenticated;

  @override
  void initState() {
    super.initState();
    checkAuth();
  }

  Future<void> checkAuth() async {
    final token = await ApiService.getToken();
    setState(() {
      isAuthenticated = token != null && token.isNotEmpty;
    });
  }

  @override
  Widget build(BuildContext context) {
    if (isAuthenticated == null) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    if (!isAuthenticated!) {
      return AuthScreen(onLoginSuccess: checkAuth);
    }
    return MainNavigationScreen(onLogout: () async {
      await ApiService.logout();
      checkAuth();
    });
  }
}

class MainNavigationScreen extends StatefulWidget {
  final VoidCallback onLogout;
  const MainNavigationScreen({super.key, required this.onLogout});

  @override
  State<MainNavigationScreen> createState() => _MainNavigationScreenState();
}

class _MainNavigationScreenState extends State<MainNavigationScreen> {
  int _selectedIndex = 0;
  String? supportUrl;

  @override
  void initState() {
    super.initState();
    _loadConfig();
  }

  Future<void> _loadConfig() async {
    final cfg = await ApiService.fetchStoreConfig();
    if (!mounted) return;
    setState(() => supportUrl = cfg['support_url']?.toString());
  }

  Future<void> _contact() async {
    final ok = await openTelegramSupport(supportUrl);
    if (!ok && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Telegram ကို ဖွင့်မရပါ။ Telegram app ထည့်သွင်းထားခြင်း ရှိမရှိ စစ်ပါ။')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final pages = [
      const ShopScreen(),
      const OrdersScreen(),
      const WalletScreen(),
      ProfileScreen(onLogout: widget.onLogout, onContact: _contact),
    ];

    return Scaffold(
      body: pages[_selectedIndex],
      floatingActionButton: _selectedIndex == 3
          ? null
          : FloatingActionButton.extended(
              onPressed: _contact,
              backgroundColor: const Color(0xFF229ED9),
              foregroundColor: Colors.white,
              icon: const Icon(Icons.send_rounded, size: 20),
              label: const Text('ဆက်သွယ်ရန်', style: TextStyle(fontWeight: FontWeight.w700)),
            ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _selectedIndex,
        onDestinationSelected: (idx) => setState(() => _selectedIndex = idx),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.storefront_outlined), selectedIcon: Icon(Icons.storefront_rounded), label: 'Shop'),
          NavigationDestination(icon: Icon(Icons.receipt_long_outlined), selectedIcon: Icon(Icons.receipt_long_rounded), label: 'Orders'),
          NavigationDestination(icon: Icon(Icons.account_balance_wallet_outlined), selectedIcon: Icon(Icons.account_balance_wallet_rounded), label: 'Wallet'),
          NavigationDestination(icon: Icon(Icons.person_outline_rounded), selectedIcon: Icon(Icons.person_rounded), label: 'Profile'),
        ],
      ),
    );
  }
}
