import 'dart:io';
import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import '../api_service.dart';

class WalletScreen extends StatefulWidget {
  final VoidCallback onLogout;
  const WalletScreen({super.key, required this.onLogout});

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
      builder: (_) => AlertDialog(
        title: const Text('Top-Up Wallet Balance'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: amountCtrl,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(labelText: 'Amount (MMK)'),
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              value: method,
              items: const [
                DropdownMenuItem(value: 'KPay', child: Text('KBZPay')),
                DropdownMenuItem(value: 'WavePay', child: Text('WavePay')),
              ],
              onChanged: (v) => method = v!,
            ),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
          ElevatedButton.icon(
            onPressed: () async {
              final amt = double.tryParse(amountCtrl.text.trim()) ?? 0;
              final picker = ImagePicker();
              final picked = await picker.pickImage(source: ImageSource.gallery);
              if (picked == null) return;
              Navigator.pop(context);
              final res = await ApiService.uploadWalletTopup(
                amount: amt,
                method: method,
                imageFile: File(picked.path),
              );
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(content: Text(res['message'] ?? res['error'] ?? 'Done')),
              );
            },
            icon: const Icon(Icons.upload),
            label: const Text('Pick Receipt & Submit'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Wallet & VIP Membership', style: TextStyle(fontWeight: FontWeight.bold)),
        actions: [
          IconButton(icon: const Icon(Icons.logout), onPressed: widget.onLogout, tooltip: 'Logout'),
        ],
      ),
      body: loading
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: loadProfile,
              child: ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  Container(
                    padding: const EdgeInsets.all(20),
                    decoration: BoxDecoration(
                      gradient: const LinearGradient(
                        colors: [Color(0xFF0F766E), Color(0xFF1E293B)],
                        begin: Alignment.topLeft,
                        end: Alignment.bottomRight,
                      ),
                      borderRadius: BorderRadius.circular(18),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('User ID: ${profile?['user_id'] ?? '-'}', style: const TextStyle(color: Colors.white70)),
                        const SizedBox(height: 6),
                        Text(
                          '${profile?['balance'] ?? 0} MMK',
                          style: const TextStyle(fontSize: 30, fontWeight: FontWeight.bold),
                        ),
                        const SizedBox(height: 8),
                        Text(
                          'Tier: ${profile?['tier'] ?? 'Regular Member'}',
                          style: const TextStyle(color: Colors.amberAccent, fontWeight: FontWeight.w600),
                        ),
                        const SizedBox(height: 16),
                        Row(
                          children: [
                            ElevatedButton.icon(
                              onPressed: showTopupDialog,
                              icon: const Icon(Icons.add_card),
                              label: const Text('Top-Up Balance'),
                            ),
                            const SizedBox(width: 12),
                            OutlinedButton.icon(
                              onPressed: doCheckin,
                              icon: const Icon(Icons.calendar_today, size: 16),
                              label: Text('Check-in (${profile?['streak'] ?? 0}d)'),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 16),
                  Card(
                    color: const Color(0xFF1E293B),
                    child: ListTile(
                      leading: const Icon(Icons.stars, color: Colors.amber, size: 36),
                      title: Text('Reward Points: ${profile?['points'] ?? 0} pts'),
                      subtitle: const Text('500 Points = 1,000 MMK Wallet Balance'),
                      trailing: ElevatedButton(
                        onPressed: doRedeem,
                        child: const Text('Redeem'),
                      ),
                    ),
                  ),
                  const SizedBox(height: 8),
                  Card(
                    color: const Color(0xFF1E293B),
                    child: ListTile(
                      leading: const Icon(Icons.shopping_bag, color: Color(0xFF38BDF8), size: 32),
                      title: Text('Total Completed Orders: ${profile?['total_orders'] ?? 0}'),
                      subtitle: Text('Total Spent: ${profile?['total_spent'] ?? 0} MMK'),
                    ),
                  ),
                ],
              ),
            ),
    );
  }
}
