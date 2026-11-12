import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../api_service.dart';
import '../theme.dart';

class OrdersScreen extends StatefulWidget {
  const OrdersScreen({super.key});

  @override
  State<OrdersScreen> createState() => _OrdersScreenState();
}

class _OrdersScreenState extends State<OrdersScreen> {
  List<dynamic> orders = [];
  bool loading = true;
  bool failed = false;

  @override
  void initState() {
    super.initState();
    loadOrders();
  }

  Future<void> loadOrders() async {
    setState(() {
      loading = true;
      failed = false;
    });
    try {
      final dash = await ApiService.fetchDashboard();
      if (!mounted) return;
      setState(() {
        orders = dash['orders'] ?? [];
        loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        loading = false;
        failed = true;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('My Orders'),
        actions: [
          IconButton(icon: const Icon(Icons.refresh_rounded), onPressed: loadOrders),
        ],
      ),
      body: loading
          ? const Center(child: CircularProgressIndicator())
          : failed
              ? Center(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Icon(Icons.cloud_off_rounded, size: 52, color: AppColors.textDim),
                      const SizedBox(height: 10),
                      const Text('Server နဲ့ ချိတ်ဆက်လို့မရပါ'),
                      const SizedBox(height: 12),
                      FilledButton.icon(
                        onPressed: loadOrders,
                        icon: const Icon(Icons.refresh_rounded),
                        label: const Text('Retry'),
                      ),
                    ],
                  ),
                )
              : orders.isEmpty
                  ? const Center(
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(Icons.inventory_2_outlined, size: 56, color: AppColors.textDim),
                          SizedBox(height: 10),
                          Text('မှာယူထားတာ မရှိသေးပါ', style: TextStyle(fontWeight: FontWeight.w700)),
                          SizedBox(height: 4),
                          Text('ဝယ်ပြီးသား account/key များ ဒီမှာ ပေါ်ပါမယ်',
                              style: TextStyle(color: AppColors.textDim, fontSize: 12.5)),
                        ],
                      ),
                    )
                  : RefreshIndicator(
                      onRefresh: loadOrders,
                      child: ListView.builder(
                        padding: const EdgeInsets.fromLTRB(16, 8, 16, 100),
                        itemCount: orders.length,
                        itemBuilder: (context, idx) => Padding(
                          padding: const EdgeInsets.only(bottom: 12),
                          child: _OrderCard(order: Map<String, dynamic>.from(orders[idx] as Map)),
                        ),
                      ),
                    ),
    );
  }
}

class _OrderCard extends StatelessWidget {
  final Map<String, dynamic> order;
  const _OrderCard({required this.order});

  @override
  Widget build(BuildContext context) {
    final o = order;
    final name = '${o['item_name'] ?? ''}'.replaceAll('‎', '').trim();
    final usage = o['outline_usage'] is Map ? Map<String, dynamic>.from(o['outline_usage'] as Map) : null;
    final delivered = '${o['delivered_data'] ?? ''}'.trim();

    return SectionCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              IconTile(icon: iconForProduct(name), color: colorForProduct(name), size: 42),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(name,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800)),
                    const SizedBox(height: 2),
                    Text('${o['order_code'] ?? ''}  •  x${o['quantity'] ?? 1}',
                        style: const TextStyle(fontSize: 11.5, color: AppColors.textDim)),
                  ],
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
                decoration: BoxDecoration(
                  color: AppColors.ok.withAlpha(35),
                  borderRadius: BorderRadius.circular(20),
                ),
                child: const Text('Delivered',
                    style: TextStyle(fontSize: 11, fontWeight: FontWeight.w800, color: AppColors.ok)),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 14,
            runSpacing: 4,
            children: [
              _meta(Icons.event_rounded, 'Expiry: ${o['expiry_date'] ?? '-'}', AppColors.warn),
              _meta(Icons.payments_outlined, '${fmtMoney(o['total_amount'])} Ks', AppColors.textDim),
              _meta(Icons.schedule_rounded, '${o['timestamp'] ?? ''}', AppColors.textDim),
            ],
          ),
          if (usage != null) ...[
            const SizedBox(height: 12),
            Text(
              usage['limit_gb'] != null
                  ? 'Usage: ${usage['used_gb']} GB / ${usage['limit_gb']} GB (${usage['percent']}%)'
                  : 'Usage: ${usage['used_gb']} GB (Unlimited)',
              style: const TextStyle(fontSize: 12.5, color: AppColors.accent, fontWeight: FontWeight.w600),
            ),
            if (usage['limit_gb'] != null) ...[
              const SizedBox(height: 6),
              ClipRRect(
                borderRadius: BorderRadius.circular(6),
                child: LinearProgressIndicator(
                  minHeight: 7,
                  value: (((usage['percent'] ?? 0) as num).toDouble() / 100.0).clamp(0.0, 1.0),
                  backgroundColor: AppColors.surfaceHi,
                  color: AppColors.primary,
                ),
              ),
            ],
          ],
          const SizedBox(height: 12),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: AppColors.bg,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: AppColors.border),
            ),
            child: SelectableText(
              delivered.isEmpty ? 'Pending delivery' : delivered,
              style: const TextStyle(fontFamily: 'monospace', fontSize: 12.5, height: 1.4),
            ),
          ),
          if (delivered.isNotEmpty)
            Align(
              alignment: Alignment.centerRight,
              child: TextButton.icon(
                onPressed: () {
                  Clipboard.setData(ClipboardData(text: delivered));
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('Copied account/key to clipboard!')),
                  );
                },
                icon: const Icon(Icons.copy_rounded, size: 16),
                label: const Text('Copy Account / Key'),
              ),
            ),
        ],
      ),
    );
  }

  Widget _meta(IconData icon, String text, Color color) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 14, color: color),
        const SizedBox(width: 4),
        Text(text, style: TextStyle(fontSize: 11.5, color: color)),
      ],
    );
  }
}
