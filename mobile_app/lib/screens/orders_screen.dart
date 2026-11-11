import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../api_service.dart';

class OrdersScreen extends StatefulWidget {
  const OrdersScreen({super.key});

  @override
  State<OrdersScreen> createState() => _OrdersScreenState();
}

class _OrdersScreenState extends State<OrdersScreen> {
  List<dynamic> orders = [];
  bool loading = true;

  @override
  void initState() {
    super.initState();
    loadOrders();
  }

  Future<void> loadOrders() async {
    setState(() => loading = true);
    try {
      final dash = await ApiService.fetchDashboard();
      setState(() {
        orders = dash['orders'] ?? [];
        loading = false;
      });
    } catch (e) {
      setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('My Delivered Orders & Keys', style: TextStyle(fontWeight: FontWeight.bold)),
        actions: [
          IconButton(icon: const Icon(Icons.refresh), onPressed: loadOrders),
        ],
      ),
      body: loading
          ? const Center(child: CircularProgressIndicator())
          : orders.isEmpty
              ? const Center(child: Text('No completed orders yet.'))
              : RefreshIndicator(
                  onRefresh: loadOrders,
                  child: ListView.builder(
                    padding: const EdgeInsets.all(12),
                    itemCount: orders.length,
                    itemBuilder: (context, idx) {
                      final o = orders[idx];
                      final usage = o['outline_usage'] as Map<String, dynamic>?;

                      return Card(
                        color: const Color(0xFF1E293B),
                        margin: const EdgeInsets.only(bottom: 12),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                        child: Padding(
                          padding: const EdgeInsets.all(16),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                                children: [
                                  Expanded(
                                    child: Text(
                                      o['item_name'] ?? '',
                                      style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold),
                                    ),
                                  ),
                                  Text(
                                    o['order_code'] ?? '',
                                    style: const TextStyle(fontSize: 12, color: Colors.white54),
                                  ),
                                ],
                              ),
                              const SizedBox(height: 6),
                              Text('Expiry: ${o['expiry_date']}', style: const TextStyle(fontSize: 13, color: Colors.amberAccent)),
                              if (usage != null) ...[
                                const SizedBox(height: 10),
                                Text(
                                  usage['limit_gb'] != null
                                      ? 'Outline VPN Usage: ${usage['used_gb']} GB / ${usage['limit_gb']} GB (${usage['percent']}%)'
                                      : 'Outline VPN Usage: ${usage['used_gb']} GB (Unlimited)',
                                  style: const TextStyle(fontSize: 13, color: Color(0xFF38BDF8)),
                                ),
                                const SizedBox(height: 6),
                                if (usage['limit_gb'] != null)
                                  LinearProgressIndicator(
                                    value: ((usage['percent'] ?? 0) as num).toDouble() / 100.0,
                                    backgroundColor: Colors.black38,
                                    color: const Color(0xFF14B8A6),
                                  ),
                              ],
                              const Divider(height: 20),
                              Container(
                                width: double.infinity,
                                padding: const EdgeInsets.all(12),
                                decoration: BoxDecoration(
                                  color: Colors.black38,
                                  borderRadius: BorderRadius.circular(10),
                                ),
                                child: SelectableText(
                                  o['delivered_data'] ?? 'Pending delivery',
                                  style: const TextStyle(fontFamily: 'monospace', fontSize: 13),
                                ),
                              ),
                              const SizedBox(height: 8),
                              Align(
                                alignment: Alignment.centerRight,
                                child: TextButton.icon(
                                  onPressed: () {
                                    Clipboard.setData(ClipboardData(text: o['delivered_data'] ?? ''));
                                    ScaffoldMessenger.of(context).showSnackBar(
                                      const SnackBar(content: Text('Copied account/key to clipboard!')),
                                    );
                                  },
                                  icon: const Icon(Icons.copy, size: 16),
                                  label: const Text('Copy Account / Key'),
                                ),
                              ),
                            ],
                          ),
                        ),
                      );
                    },
                  ),
                ),
    );
  }
}
