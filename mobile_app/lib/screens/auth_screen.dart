import 'package:flutter/material.dart';
import '../api_service.dart';

class AuthScreen extends StatefulWidget {
  final VoidCallback onLoginSuccess;
  const AuthScreen({super.key, required this.onLoginSuccess});

  @override
  State<AuthScreen> createState() => _AuthScreenState();
}

class _AuthScreenState extends State<AuthScreen> {
  bool isLogin = true;
  bool loading = false;
  final nameCtrl = TextEditingController();
  final phoneCtrl = TextEditingController();
  final passCtrl = TextEditingController();
  final tgIdCtrl = TextEditingController();

  Future<void> submit() async {
    setState(() => loading = true);
    Map<String, dynamic> res;
    if (isLogin) {
      res = await ApiService.login(phoneCtrl.text.trim(), passCtrl.text.trim());
    } else {
      final tgId = int.tryParse(tgIdCtrl.text.trim());
      res = await ApiService.register(
        fullName: nameCtrl.text.trim().isEmpty ? 'App User' : nameCtrl.text.trim(),
        phoneOrEmail: phoneCtrl.text.trim(),
        password: passCtrl.text.trim(),
        telegramUserId: tgId,
      );
    }
    setState(() => loading = false);

    if (res['ok'] == true) {
      widget.onLoginSuccess();
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(res['error'] ?? 'Authentication error'), backgroundColor: Colors.redAccent),
      );
    }
  }

  Future<void> showServerConfigDialog() async {
    final current = await ApiService.getBaseUrl();
    final ctrl = TextEditingController(text: current);
    await showDialog(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Server API URL'),
        content: TextField(
          controller: ctrl,
          decoration: const InputDecoration(hintText: 'https://your-domain.com/api'),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
          ElevatedButton(
            onPressed: () async {
              await ApiService.setCustomBaseUrl(ctrl.text);
              Navigator.pop(context);
              ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('API URL Saved!')));
            },
            child: const Text('Save'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        backgroundColor: Colors.transparent,
        actions: [
          IconButton(
            icon: const Icon(Icons.settings_ethernet),
            tooltip: 'Configure Server URL',
            onPressed: showServerConfigDialog,
          ),
        ],
      ),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Icon(Icons.diamond_rounded, size: 72, color: Color(0xFF14B8A6)),
              const SizedBox(height: 12),
              const Text(
                'ENI PREMIUM STORE',
                style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold, letterSpacing: 1.2),
              ),
              const SizedBox(height: 6),
              Text(
                isLogin ? 'Sign in to access your digital subscriptions' : 'Create a new ENI Store account',
                style: const TextStyle(color: Colors.white70),
              ),
              const SizedBox(height: 28),
              if (!isLogin) ...[
                TextField(
                  controller: nameCtrl,
                  decoration: const InputDecoration(
                    labelText: 'Your Name',
                    prefixIcon: Icon(Icons.person_outline),
                    border: OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 14),
              ],
              TextField(
                controller: phoneCtrl,
                decoration: const InputDecoration(
                  labelText: 'Phone Number or Username',
                  prefixIcon: Icon(Icons.alternate_email),
                  border: OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 14),
              TextField(
                controller: passCtrl,
                obscureText: true,
                decoration: const InputDecoration(
                  labelText: 'Password',
                  prefixIcon: Icon(Icons.lock_outline),
                  border: OutlineInputBorder(),
                ),
              ),
              if (!isLogin) ...[
                const SizedBox(height: 14),
                TextField(
                  controller: tgIdCtrl,
                  keyboardType: TextInputType.number,
                  decoration: const InputDecoration(
                    labelText: 'Telegram User ID (Optional - to sync Bot orders)',
                    prefixIcon: Icon(Icons.telegram),
                    border: OutlineInputBorder(),
                  ),
                ),
              ],
              const SizedBox(height: 24),
              SizedBox(
                width: double.infinity,
                height: 50,
                child: ElevatedButton(
                  onPressed: loading ? null : submit,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFF14B8A6),
                    foregroundColor: Colors.black,
                  ),
                  child: loading
                      ? const CircularProgressIndicator(color: Colors.black)
                      : Text(isLogin ? 'LOGIN' : 'CREATE ACCOUNT', style: const TextStyle(fontWeight: FontWeight.bold)),
                ),
              ),
              const SizedBox(height: 16),
              TextButton(
                onPressed: () => setState(() => isLogin = !isLogin),
                child: Text(isLogin ? "Don't have an account? Register Now" : 'Already have an account? Login'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
