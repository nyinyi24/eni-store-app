import 'dart:io';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import '../api_service.dart';
import '../theme.dart';

class WalletScreen extends StatefulWidget {
  const WalletScreen({super.key});

  @override
  State<WalletScreen> createState() => _WalletScreenState();
}

class _WalletScreenState extends State<WalletScreen> {
  Map<String, dynamic>? profile;
  bool loading = true;

  @override
  void initState() {
    super.initState();
    loadProfile();
  }

  Future<void> loadProfile() async {
    setState(() => loading = true);
    try {
      final dash = await ApiService.fetchDashboard();
      setState(() {
        profile = dash['profile'];
        loading = false;
      });
    } catch (e) {
      setState(() => loading = false);
    }
  }

  Future<void> doCheckin() async {
    final res = await ApiService.claimDailyCheckin();
    if (res['ok'] == true) {
      loadProfile();
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('🎉 Daily Check-in: +${res['data']['earned']} Points!'),
          backgroundColor: Colors.green,
        ),
      );
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(res['error'] ?? 'Already checked in')),
      );
    }
  }

  Future<void> doRedeem() async {
    final res = await ApiService.redeemPoints();
    if (res['ok'] == true) {
      loadProfile();
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('🎉 Redeemed 500 Points for 1,000 MMK Wallet Balance!'),
          backgroundColor: Colors.green,
        ),
      );
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(res['error'] ?? 'Redeem failed')),
      );
    }
  }

  Future<void> showTopupDialog() async {
    final amountCtrl = TextEditingController(text: '10000');
    String method = 'KPay';
    await showDialog(
      context: context,
      builder: (_) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          backgroundColor: AppColors.surface,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
          title: const Text('Top-Up Wallet'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              TextField(
                controller: amountCtrl,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(
                  labelText: 'Amount (MMK)',
                  prefixIcon: Icon(Icons.payments_outlined),
                ),
              ),
              const SizedBox(height: 14),
              Wrap(
                spacing: 8,
                children: [
                  ChoiceChip(
                    label: const Text('KBZPay'),
                    selected: method == 'KPay',
                    onSelected: (_) => setLocal(() => method = 'KPay'),
                  ),
                  ChoiceChip(
                    label: const Text('WavePay'),
                    selected: method == 'WavePay',
                    onSelected: (_) => setLocal(() => method = 'WavePay'),
                  ),
                ],
              ),
            ],
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
            FilledButton.icon(
              onPressed: () async {
                final amt = double.tryParse(amountCtrl.text.trim()) ?? 0;
                final picker = ImagePicker();
                final picked = await picker.pickImage(source: ImageSource.gallery);
                if (picked == null) return;
                if (ctx.mounted) Navigator.pop(ctx);
                final res = await ApiService.uploadWalletTopup(
                  amount: amt,
                  method: method,
                  imageFile: File(picked.path),
                );
                if (!mounted) return;
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(content: Text(res['message'] ?? res['error'] ?? 'Done')),
                );
              },
              icon: const Icon(Icons.upload_rounded),
              label: const Text('Receipt & Submit'),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Wallet & Rewards'),
        actions: [
          IconButton(icon: const Icon(Icons.refresh_rounded), onPressed: loadProfile),
        ],
      ),
      body: loading
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: loadProfile,
              child: ListView(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 100),
                children: [
                  Container(
                    padding: const EdgeInsets.all(20),
                    decoration: BoxDecoration(
                      gradient: const LinearGradient(
                        colors: [Color(0xFF0F766E), Color(0xFF155E75), Color(0xFF1E3A8A)],
                        begin: Alignment.topLeft,
                        end: Alignment.bottomRight,
                      ),
                      borderRadius: BorderRadius.circular(22),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            const Text('Wallet Balance', style: TextStyle(color: Colors.white70)),
                            Icon(Icons.account_balance_wallet_rounded, color: Colors.white.withAlpha(200)),
                          ],
                        ),
                        const SizedBox(height: 6),
                        Text(
                          '${fmtMoney(profile?['balance'] ?? 0)} Ks',
                          style: const TextStyle(fontSize: 34, fontWeight: FontWeight.w800),
                        ),
                        const SizedBox(height: 8),
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                          decoration: BoxDecoration(
                            color: Colors.white.withAlpha(35),
                            borderRadius: BorderRadius.circular(20),
                          ),
                          child: Text(
                            '${profile?['tier'] ?? 'Regular Member'}',
                            style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700),
                          ),
                        ),
                        const SizedBox(height: 18),
                        Row(
                          children: [
                            Expanded(
                              child: FilledButton.icon(
                                onPressed: showTopupDialog,
                                icon: const Icon(Icons.add_card_rounded, size: 18),
                                label: const Text('Top-Up'),
                                style: FilledButton.styleFrom(
                                  backgroundColor: Colors.white,
                                  foregroundColor: Colors.black,
                                  minimumSize: const Size.fromHeight(44),
                                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                                ),
                              ),
                            ),
                            const SizedBox(width: 10),
                            Expanded(
                              child: OutlinedButton.icon(
                                onPressed: doCheckin,
                                icon: const Icon(Icons.event_available_rounded, size: 18),
                                label: Text('Check-in (${profile?['streak'] ?? 0}d)'),
                                style: OutlinedButton.styleFrom(
                                  foregroundColor: Colors.white,
                                  side: const BorderSide(color: Colors.white54),
                                  minimumSize: const Size.fromHeight(44),
                                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                                ),
                              ),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 14),
                  SectionCard(
                    child: Row(
                      children: [
                        const IconTile(icon: Icons.stars_rounded, color: AppColors.warn),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text('${profile?['points'] ?? 0} pts',
                                  style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
                              Text('500 Points = 1,000 Ks Wallet',
                                  style: TextStyle(fontSize: 12, color: AppColors.textDim)),
                            ],
                          ),
                        ),
                        FilledButton(
                          onPressed: doRedeem,
                          style: FilledButton.styleFrom(
                            backgroundColor: AppColors.warn,
                            foregroundColor: Colors.black,
                            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                          ),
                          child: const Text('Redeem', style: TextStyle(fontWeight: FontWeight.w800)),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      Expanded(
                        child: _StatBox(
                          icon: Icons.shopping_bag_rounded,
                          color: AppColors.accent,
                          value: '${profile?['total_orders'] ?? 0}',
                          label: 'Completed Orders',
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: _StatBox(
                          icon: Icons.savings_rounded,
                          color: AppColors.ok,
                          value: '${fmtMoney(profile?['total_spent'] ?? 0)} Ks',
                          label: 'Total Spent',
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
    );
  }
}

class _StatBox extends StatelessWidget {
  final IconData icon;
  final Color color;
  final String value;
  final String label;
  const _StatBox({required this.icon, required this.color, required this.value, required this.label});

  @override
  Widget build(BuildContext context) {
    return SectionCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: color),
          const SizedBox(height: 10),
          Text(value,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
          Text(label, style: TextStyle(fontSize: 12, color: AppColors.textDim)),
        ],
      ),
    );
  }
}