import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../api_service.dart';
import '../theme.dart';

class ProfileScreen extends StatefulWidget {
  final VoidCallback onLogout;
  final Future<void> Function() onContact;
  const ProfileScreen({super.key, required this.onLogout, required this.onContact});

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  Map<String, dynamic>? profile;
  bool loading = true;

  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    setState(() => loading = true);
    try {
      final dash = await ApiService.fetchDashboard();
      if (!mounted) return;
      setState(() {
        profile = dash['profile'] is Map ? Map<String, dynamic>.from(dash['profile'] as Map) : null;
        loading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() => loading = false);
    }
  }

  Future<void> confirmLogout() async {
    final yes = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppColors.surface,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        title: const Text('Logout'),
        content: const Text('Account ကနေ ထွက်မှာ သေချာပါသလား?'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            style: FilledButton.styleFrom(backgroundColor: AppColors.danger),
            child: const Text('Logout'),
          ),
        ],
      ),
    );
    if (yes == true) widget.onLogout();
  }

  @override
  Widget build(BuildContext context) {
    final userId = '${profile?['user_id'] ?? '-'}';
    return Scaffold(
      appBar: AppBar(title: const Text('Profile')),
      body: loading
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: load,
              child: ListView(
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 40),
                children: [
                  SectionCard(
                    padding: const EdgeInsets.all(20),
                    child: Column(
                      children: [
                        Container(
                          width: 84,
                          height: 84,
                          decoration: const BoxDecoration(
                            shape: BoxShape.circle,
                            gradient: LinearGradient(
                              begin: Alignment.topLeft,
                              end: Alignment.bottomRight,
                              colors: [AppColors.primary, AppColors.accent],
                            ),
                          ),
                          child: const Icon(Icons.person_rounded, size: 46, color: Colors.black87),
                        ),
                        const SizedBox(height: 12),
                        Text('ID: $userId',
                            style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
                        const SizedBox(height: 8),
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
                          decoration: BoxDecoration(
                            color: AppColors.warn.withAlpha(35),
                            borderRadius: BorderRadius.circular(20),
                          ),
                          child: Text(
                            '${profile?['tier'] ?? 'Regular Member'}',
                            style: const TextStyle(
                                fontSize: 12.5, fontWeight: FontWeight.w700, color: AppColors.warn),
                          ),
                        ),
                        const SizedBox(height: 18),
                        Row(
                          children: [
                            _stat('${profile?['total_orders'] ?? 0}', 'Orders'),
                            _divider(),
                            _stat('${profile?['points'] ?? 0}', 'Points'),
                            _divider(),
                            _stat('${fmtMoney(profile?['balance'] ?? 0)}', 'Balance (Ks)'),
                          ],
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 16),
                  _sectionLabel('ဆက်သွယ်ရန်'),
                  _tile(
                    icon: Icons.send_rounded,
                    color: const Color(0xFF229ED9),
                    title: 'Telegram မှာ တိုက်ရိုက်ပို့မယ်',
                    subtitle: 'မေးစရာ၊ ပြဿနာရှိရင် Admin ကို ဆက်သွယ်ပါ',
                    onTap: widget.onContact,
                  ),
                  const SizedBox(height: 16),
                  _sectionLabel('Account'),
                  _tile(
                    icon: Icons.copy_rounded,
                    color: AppColors.accent,
                    title: 'User ID ကူးယူမယ်',
                    subtitle: userId,
                    onTap: () async {
                      await Clipboard.setData(ClipboardData(text: userId));
                      if (!mounted) return;
                      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Copied!')));
                    },
                  ),
                  const SizedBox(height: 8),
                  _tile(
                    icon: Icons.logout_rounded,
                    color: AppColors.danger,
                    title: 'Logout',
                    subtitle: 'Account ကနေ ထွက်မယ်',
                    onTap: confirmLogout,
                  ),
                  const SizedBox(height: 24),
                  const Center(
                    child: Text('ENI Premium Store  •  v1.0.0',
                        style: TextStyle(fontSize: 11.5, color: AppColors.textDim)),
                  ),
                ],
              ),
            ),
    );
  }

  Widget _sectionLabel(String t) => Padding(
        padding: const EdgeInsets.fromLTRB(4, 0, 4, 8),
        child: Text(t, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: AppColors.textDim)),
      );

  Widget _stat(String value, String label) => Expanded(
        child: Column(
          children: [
            Text(value,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
            const SizedBox(height: 2),
            Text(label, style: const TextStyle(fontSize: 11.5, color: AppColors.textDim)),
          ],
        ),
      );

  Widget _divider() => Container(width: 1, height: 30, color: AppColors.border);

  Widget _tile({
    required IconData icon,
    required Color color,
    required String title,
    required String subtitle,
    required VoidCallback onTap,
  }) {
    return Material(
      color: AppColors.surface,
      borderRadius: BorderRadius.circular(16),
      child: InkWell(
        borderRadius: BorderRadius.circular(16),
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: AppColors.border),
          ),
          child: Row(
            children: [
              IconTile(icon: icon, color: color, size: 42),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title, style: const TextStyle(fontSize: 14.5, fontWeight: FontWeight.w700)),
                    const SizedBox(height: 2),
                    Text(subtitle,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontSize: 12, color: AppColors.textDim)),
                  ],
                ),
              ),
              const Icon(Icons.chevron_right_rounded, color: AppColors.textDim),
            ],
          ),
        ),
      ),
    );
  }
}
