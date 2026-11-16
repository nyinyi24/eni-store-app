import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../api_service.dart';
import '../theme.dart';
import '../notifications.dart';

class ProfileScreen extends StatefulWidget {
  final VoidCallback onLogout;
  final Future<void> Function() onContact;
  const ProfileScreen({super.key, required this.onLogout, required this.onContact});

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  Map<String, dynamic>? profile; // wallet / tier stats
  Map<String, dynamic>? account; // name, login id, telegram link
  bool loading = true;
  bool failed = false;

  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    setState(() {
      loading = true;
      failed = false;
    });
    try {
      final dash = await ApiService.fetchDashboard();
      final acc = await ApiService.fetchAccount();
      if (!mounted) return;
      setState(() {
        profile = dash['profile'] is Map ? Map<String, dynamic>.from(dash['profile'] as Map) : null;
        account = acc['ok'] == true ? Map<String, dynamic>.from(acc['data'] as Map) : null;
        loading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        loading = false;
        failed = true;
      });
    }
  }

  void _snack(String msg, {Color? color}) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg), backgroundColor: color));
  }

  String get _name => '${account?['full_name'] ?? 'App User'}';
  bool get _tgLinked => account?['telegram_linked'] == true;

  // ---------------- dialogs ----------------

  Future<void> editName() async {
    final ctrl = TextEditingController(text: _name);
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        title: const Text('Edit Profile'),
        content: TextField(
          controller: ctrl,
          textCapitalization: TextCapitalization.words,
          decoration: const InputDecoration(labelText: 'Your Name', prefixIcon: Icon(Icons.person_outline_rounded)),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Save')),
        ],
      ),
    );
    if (ok != true) return;
    final res = await ApiService.updateProfileName(ctrl.text.trim());
    if (!mounted) return;
    if (res['ok'] == true) {
      _snack('နာမည် ပြောင်းပြီးပါပြီ', color: Colors.green);
      load();
    } else {
      _snack('${res['error']}', color: Colors.redAccent);
    }
  }

  Future<void> changePassword() async {
    final oldCtrl = TextEditingController();
    final newCtrl = TextEditingController();
    final confirmCtrl = TextEditingController();
    String? error;
    bool busy = false;
    await showDialog(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
          title: const Text('Change Password'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextField(
                  controller: oldCtrl,
                  obscureText: true,
                  decoration: const InputDecoration(labelText: 'Current password', prefixIcon: Icon(Icons.lock_outline_rounded)),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: newCtrl,
                  obscureText: true,
                  decoration: const InputDecoration(labelText: 'New password', prefixIcon: Icon(Icons.lock_reset_rounded)),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: confirmCtrl,
                  obscureText: true,
                  decoration: const InputDecoration(labelText: 'Confirm new password', prefixIcon: Icon(Icons.check_rounded)),
                ),
                if (error != null) ...[
                  const SizedBox(height: 10),
                  Text(error!, style: const TextStyle(color: AppColors.danger, fontSize: 12.5)),
                ],
              ],
            ),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
            FilledButton(
              onPressed: busy
                  ? null
                  : () async {
                      if (newCtrl.text.length < 4) {
                        setLocal(() => error = 'Password အသစ်သည် အနည်းဆုံး ၄ လုံး ရှိရပါမည်။');
                        return;
                      }
                      if (newCtrl.text != confirmCtrl.text) {
                        setLocal(() => error = 'Password အသစ် နှစ်ခု မတူပါ။');
                        return;
                      }
                      setLocal(() {
                        busy = true;
                        error = null;
                      });
                      final res = await ApiService.changePassword(oldCtrl.text, newCtrl.text);
                      if (res['ok'] == true) {
                        if (ctx.mounted) Navigator.pop(ctx);
                        if (mounted) _snack('Password ပြောင်းပြီးပါပြီ', color: Colors.green);
                      } else {
                        setLocal(() {
                          busy = false;
                          error = '${res['error']}';
                        });
                      }
                    },
              child: const Text('Update'),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> linkTelegram() async {
    final idCtrl = TextEditingController();
    final codeCtrl = TextEditingController();
    bool codeSent = false;
    bool busy = false;
    String? error;
    bool success = false;

    await showDialog(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
          title: const Text('Link Telegram'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  codeSent
                      ? 'Telegram Bot ဆီကို code ပို့လိုက်ပါပြီ။ ရောက်လာတဲ့ ၆ လုံး code ကို ထည့်ပါ။'
                      : 'Bot ထဲမှာ ရှိပြီးသား balance၊ points၊ order တွေကို ဒီ account ထဲ ပေါင်းထည့်ပေးပါမယ်။\n\n'
                          '၁။ Telegram Bot ကို /start လုပ်ထားပါ\n'
                          '၂။ သင့် Telegram User ID ကို ထည့်ပါ\n'
                          '၃။ Bot က ပို့တဲ့ code ကို ထည့်ပြီး အတည်ပြုပါ',
                  style: TextStyle(fontSize: 12.5, color: AppColors.textDim, height: 1.45),
                ),
                const SizedBox(height: 14),
                if (!codeSent)
                  TextField(
                    controller: idCtrl,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                      labelText: 'Telegram User ID',
                      hintText: 'e.g. 7640253919',
                      prefixIcon: Icon(Icons.send_rounded),
                    ),
                  )
                else
                  TextField(
                    controller: codeCtrl,
                    keyboardType: TextInputType.number,
                    maxLength: 6,
                    decoration: const InputDecoration(
                      labelText: '6-digit code',
                      prefixIcon: Icon(Icons.pin_rounded),
                      counterText: '',
                    ),
                  ),
                if (error != null) ...[
                  const SizedBox(height: 10),
                  Text(error!, style: const TextStyle(color: AppColors.danger, fontSize: 12.5)),
                ],
              ],
            ),
          ),
          actions: [
            TextButton(onPressed: busy ? null : () => Navigator.pop(ctx), child: const Text('Cancel')),
            FilledButton(
              onPressed: busy
                  ? null
                  : () async {
                      setLocal(() {
                        busy = true;
                        error = null;
                      });
                      if (!codeSent) {
                        final tgId = int.tryParse(idCtrl.text.trim());
                        if (tgId == null) {
                          setLocal(() {
                            busy = false;
                            error = 'Telegram User ID မှန်မှန်ကန်ကန် ထည့်ပါ။';
                          });
                          return;
                        }
                        final res = await ApiService.requestTelegramLink(tgId);
                        setLocal(() {
                          busy = false;
                          if (res['ok'] == true) {
                            codeSent = true;
                          } else {
                            error = '${res['error']}';
                          }
                        });
                      } else {
                        final res = await ApiService.verifyTelegramLink(codeCtrl.text.trim());
                        if (res['ok'] == true) {
                          success = true;
                          if (ctx.mounted) Navigator.pop(ctx);
                        } else {
                          setLocal(() {
                            busy = false;
                            error = '${res['error']}';
                          });
                        }
                      }
                    },
              child: busy
                  ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2.2))
                  : Text(codeSent ? 'Verify & Link' : 'Send Code'),
            ),
          ],
        ),
      ),
    );

    if (success && mounted) {
      _snack('Telegram ချိတ်ဆက်ပြီးပါပြီ။ Bot ထဲက balance နဲ့ order တွေ ပေါင်းထည့်ပေးပြီးပါပြီ', color: Colors.green);
      load();
    }
  }

  Future<void> confirmLogout() async {
    final yes = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
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

  // ---------------- build ----------------

  @override
  Widget build(BuildContext context) {
    final userId = '${profile?['user_id'] ?? account?['user_id'] ?? '-'}';
    final initial = _name.trim().isEmpty ? 'U' : String.fromCharCode(_name.trim().runes.first).toUpperCase();

    return Scaffold(
      appBar: AppBar(
        title: const Text('Profile'),
        actions: [
          const NotificationBell(),
          IconButton(icon: const Icon(Icons.refresh_rounded), onPressed: load),
        ],
      ),
      body: loading
          ? const Center(child: CircularProgressIndicator())
          : failed
              ? Center(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(Icons.cloud_off_rounded, size: 52, color: AppColors.textDim),
                      const SizedBox(height: 10),
                      const Text('Server နဲ့ ချိတ်ဆက်လို့မရပါ'),
                      const SizedBox(height: 12),
                      FilledButton.icon(
                        onPressed: load,
                        icon: const Icon(Icons.refresh_rounded),
                        label: const Text('Retry'),
                      ),
                      const SizedBox(height: 24),
                      TextButton.icon(
                        onPressed: confirmLogout,
                        icon: const Icon(Icons.logout_rounded),
                        label: const Text('Logout'),
                      ),
                    ],
                  ),
                )
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
                              alignment: Alignment.center,
                              decoration: const BoxDecoration(
                                shape: BoxShape.circle,
                                gradient: LinearGradient(
                                  begin: Alignment.topLeft,
                                  end: Alignment.bottomRight,
                                  colors: [AppColors.primary, AppColors.accent],
                                ),
                              ),
                              child: Text(initial,
                                  style: const TextStyle(
                                      fontSize: 36, fontWeight: FontWeight.w800, color: Colors.black87)),
                            ),
                            const SizedBox(height: 12),
                            Text(_name, style: const TextStyle(fontSize: 19, fontWeight: FontWeight.w800)),
                            const SizedBox(height: 2),
                            Text('@${account?['identifier'] ?? ''}   •   ID $userId',
                                style: TextStyle(fontSize: 12, color: AppColors.textDim)),
                            const SizedBox(height: 10),
                            Wrap(
                              spacing: 8,
                              runSpacing: 6,
                              alignment: WrapAlignment.center,
                              children: [
                                _chip('${profile?['tier'] ?? 'Regular Member'}', AppColors.warn),
                                _chip(
                                  _tgLinked ? 'Telegram linked' : 'Telegram not linked',
                                  _tgLinked ? AppColors.ok : AppColors.textDim,
                                  icon: _tgLinked ? Icons.check_circle_rounded : Icons.link_off_rounded,
                                ),
                              ],
                            ),
                            const SizedBox(height: 18),
                            Row(
                              children: [
                                _stat('${profile?['total_orders'] ?? 0}', 'Orders'),
                                _divider(),
                                _stat('${profile?['points'] ?? 0}', 'Points'),
                                _divider(),
                                _stat(fmtMoney(profile?['balance'] ?? 0), 'Balance (Ks)'),
                              ],
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(height: 18),
                      _sectionLabel('Account'),
                      _tile(
                        icon: Icons.edit_rounded,
                        color: AppColors.accent,
                        title: 'Edit Profile',
                        subtitle: 'နာမည် ပြောင်းမယ်',
                        onTap: editName,
                      ),
                      const SizedBox(height: 8),
                      _tile(
                        icon: Icons.lock_reset_rounded,
                        color: AppColors.warn,
                        title: 'Change Password',
                        subtitle: 'Password အသစ် ပြောင်းမယ်',
                        onTap: changePassword,
                      ),
                      const SizedBox(height: 8),
                      _tile(
                        icon: _tgLinked ? Icons.verified_rounded : Icons.link_rounded,
                        color: const Color(0xFF229ED9),
                        title: _tgLinked ? 'Telegram ချိတ်ထားပြီး' : 'Link Telegram Account',
                        subtitle: _tgLinked
                            ? 'Telegram ID: ${account?['telegram_user_id']}'
                            : 'Bot ထဲက balance / order တွေ ပေါင်းထည့်မယ်',
                        onTap: _tgLinked
                            ? () => _snack('ဒီ account မှာ Telegram ချိတ်ပြီးသား ဖြစ်ပါတယ်')
                            : linkTelegram,
                      ),
                      const SizedBox(height: 18),
                      _sectionLabel('Appearance'),
                      SectionCard(
                        padding: const EdgeInsets.all(14),
                        child: ValueListenableBuilder<ThemeMode>(
                          valueListenable: ThemeController.mode,
                          builder: (context, mode, _) => Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              const Row(
                                children: [
                                  Icon(Icons.brightness_6_rounded, size: 20),
                                  SizedBox(width: 8),
                                  Text('Day / Night mode', style: TextStyle(fontWeight: FontWeight.w700)),
                                ],
                              ),
                              const SizedBox(height: 12),
                              SizedBox(
                                width: double.infinity,
                                child: SegmentedButton<ThemeMode>(
                                  showSelectedIcon: false,
                                  segments: const [
                                    ButtonSegment(
                                        value: ThemeMode.light,
                                        icon: Icon(Icons.light_mode_rounded, size: 18),
                                        label: Text('Day')),
                                    ButtonSegment(
                                        value: ThemeMode.dark,
                                        icon: Icon(Icons.dark_mode_rounded, size: 18),
                                        label: Text('Night')),
                                    ButtonSegment(
                                        value: ThemeMode.system,
                                        icon: Icon(Icons.phone_android_rounded, size: 18),
                                        label: Text('Auto')),
                                  ],
                                  selected: {mode},
                                  onSelectionChanged: (s) => ThemeController.set(s.first),
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                      const SizedBox(height: 18),
                      _sectionLabel('ဆက်သွယ်ရန်'),
                      _tile(
                        icon: Icons.send_rounded,
                        color: const Color(0xFF229ED9),
                        title: 'Telegram မှာ တိုက်ရိုက်ပို့မယ်',
                        subtitle: 'မေးစရာ၊ ပြဿနာရှိရင် Admin ကို ဆက်သွယ်ပါ',
                        onTap: widget.onContact,
                      ),
                      const SizedBox(height: 8),
                      _tile(
                        icon: Icons.copy_rounded,
                        color: AppColors.accent,
                        title: 'User ID ကူးယူမယ်',
                        subtitle: userId,
                        onTap: () async {
                          await Clipboard.setData(ClipboardData(text: userId));
                          if (!mounted) return;
                          _snack('Copied!');
                        },
                      ),
                      const SizedBox(height: 18),
                      _tile(
                        icon: Icons.logout_rounded,
                        color: AppColors.danger,
                        title: 'Logout',
                        subtitle: 'Account ကနေ ထွက်မယ်',
                        onTap: confirmLogout,
                      ),
                      const SizedBox(height: 24),
                      Center(
                        child: Text('ENI Premium Store  •  v1.0.0',
                            style: TextStyle(fontSize: 11.5, color: AppColors.textDim)),
                      ),
                    ],
                  ),
                ),
    );
  }

  Widget _chip(String text, Color color, {IconData? icon}) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 11, vertical: 5),
        decoration: BoxDecoration(color: color.withAlpha(35), borderRadius: BorderRadius.circular(20)),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (icon != null) ...[Icon(icon, size: 14, color: color), const SizedBox(width: 5)],
            Text(text, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: color)),
          ],
        ),
      );

  Widget _sectionLabel(String t) => Padding(
        padding: const EdgeInsets.fromLTRB(4, 0, 4, 8),
        child: Text(t, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: AppColors.textDim)),
      );

  Widget _stat(String value, String label) => Expanded(
        child: Column(
          children: [
            Text(value,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
            const SizedBox(height: 2),
            Text(label, style: TextStyle(fontSize: 11.5, color: AppColors.textDim)),
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
                        style: TextStyle(fontSize: 12, color: AppColors.textDim)),
                  ],
                ),
              ),
              Icon(Icons.chevron_right_rounded, color: AppColors.textDim),
            ],
          ),
        ),
      ),
    );
  }
}