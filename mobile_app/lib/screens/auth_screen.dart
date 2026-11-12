import 'package:flutter/material.dart';
import '../api_service.dart';
import '../theme.dart';

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

  Future<void> submit() async {
    setState(() => loading = true);
    Map<String, dynamic> res;
    if (isLogin) {
      res = await ApiService.login(phoneCtrl.text.trim(), passCtrl.text.trim());
    } else {
      res = await ApiService.register(
        fullName: nameCtrl.text.trim().isEmpty ? 'App User' : nameCtrl.text.trim(),
        phoneOrEmail: phoneCtrl.text.trim(),
        password: passCtrl.text.trim(),
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
            icon: const Icon(Icons.settings_ethernet_rounded),
            tooltip: 'Configure Server URL',
            onPressed: showServerConfigDialog,
          ),
        ],
      ),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 420),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Container(
                  width: 84,
                  height: 84,
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(26),
                    gradient: const LinearGradient(
                      begin: Alignment.topLeft,
                      end: Alignment.bottomRight,
                      colors: [AppColors.primary, AppColors.accent],
                    ),
                  ),
                  child: const Icon(Icons.diamond_rounded, size: 46, color: Colors.black87),
                ),
                const SizedBox(height: 16),
                const Text(
                  'ENI PREMIUM STORE',
                  style: TextStyle(fontSize: 24, fontWeight: FontWeight.w800, letterSpacing: 1.2),
                ),
                const SizedBox(height: 6),
                Text(
                  isLogin ? 'Sign in to access your digital subscriptions' : 'Create a new ENI Store account',
                  textAlign: TextAlign.center,
                  style: TextStyle(color: AppColors.textDim),
                ),
                const SizedBox(height: 28),
                if (!isLogin) ...[
                  TextField(
                    controller: nameCtrl,
                    decoration: const InputDecoration(
                      labelText: 'Your Name',
                      prefixIcon: Icon(Icons.person_outline_rounded),
                    ),
                  ),
                  const SizedBox(height: 14),
                ],
                TextField(
                  controller: phoneCtrl,
                  decoration: const InputDecoration(
                    labelText: 'Phone Number or Username',
                    prefixIcon: Icon(Icons.alternate_email_rounded),
                  ),
                ),
                const SizedBox(height: 14),
                TextField(
                  controller: passCtrl,
                  obscureText: true,
                  decoration: const InputDecoration(
                    labelText: 'Password',
                    prefixIcon: Icon(Icons.lock_outline_rounded),
                  ),
                ),
                const SizedBox(height: 24),
                SizedBox(
                  width: double.infinity,
                  height: 52,
                  child: FilledButton(
                    onPressed: loading ? null : submit,
                    style: FilledButton.styleFrom(
                      backgroundColor: AppColors.primary,
                      foregroundColor: Colors.black,
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                    ),
                    child: loading
                        ? const SizedBox(
                            width: 22,
                            height: 22,
                            child: CircularProgressIndicator(color: Colors.black, strokeWidth: 2.5),
                          )
                        : Text(isLogin ? 'LOGIN' : 'CREATE ACCOUNT',
                            style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 15)),
                  ),
                ),
                const SizedBox(height: 14),
                TextButton(
                  onPressed: () => setState(() => isLogin = !isLogin),
                  child: Text(isLogin ? "Don't have an account? Register Now" : 'Already have an account? Login'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}