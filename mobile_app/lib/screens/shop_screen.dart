import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:image_picker/image_picker.dart';
import '../api_service.dart';

class ShopScreen extends StatefulWidget {
  const ShopScreen({super.key});

  @override
  State<ShopScreen> createState() => _ShopScreenState();
}

class _ShopScreenState extends State<ShopScreen> {
  List<dynamic> products = [];
  Map<String, dynamic> storeConfig = {};
  bool loading = true;
  String searchQuery = '';

  @override
  void initState() {
    super.initState();
    loadStore();
  }

  Future<void> loadStore() async {
    setState(() => loading = true);
    try {
      final prods = await ApiService.fetchProducts();
      final cfg = await ApiService.fetchStoreConfig();
      setState(() {
        products = prods;
        storeConfig = cfg;
        loading = false;
      });
    } catch (e) {
      setState(() => loading = false);
    }
  }

  void openCheckoutSheet(Map<String, dynamic> item) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: const Color(0xFF1E293B),
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (_) => CheckoutBottomSheet(item: item, storeConfig: storeConfig, onOrderSuccess: loadStore),
    );
  }

  @override
  Widget build(BuildContext context) {
    final filtered = products.where((p) {
      final name = (p['name'] ?? '').toString().toLowerCase();
      return name.contains(searchQuery.toLowerCase());
    }).toList();

    return Scaffold(
      appBar: AppBar(
        title: const Text('ENI Premium Store', style: TextStyle(fontWeight: FontWeight.bold)),
        actions: [
          IconButton(icon: const Icon(Icons.refresh), onPressed: loadStore),
        ],
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
            child: TextField(
              onChanged: (val) => setState(() => searchQuery = val),
              decoration: InputDecoration(
                hintText: 'Search VPN, Telegram Premium, Gift Cards...',
                prefixIcon: const Icon(Icons.search),
                filled: true,
                fillColor: const Color(0xFF1E293B),
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide.none),
              ),
            ),
          ),
          Expanded(
            child: loading
                ? const Center(child: CircularProgressIndicator())
                : RefreshIndicator(
                    onRefresh: loadStore,
                    child: ListView.builder(
                      padding: const EdgeInsets.all(12),
                      itemCount: filtered.length,
                      itemBuilder: (context, idx) {
                        final p = filtered[idx];
                        final int stock = p['available_stock'] ?? 0;
                        final bool hasDiscount = p['discount_percent'] != null;

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
                                        p['name'] ?? '',
                                        style: const TextStyle(fontSize: 17, fontWeight: FontWeight.bold),
                                      ),
                                    ),
                                    if (hasDiscount)
                                      Container(
                                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                                        decoration: BoxDecoration(
                                          color: Colors.redAccent,
                                          borderRadius: BorderRadius.circular(8),
                                        ),
                                        child: Text(
                                          '-${p['discount_percent']}% OFF',
                                          style: const TextStyle(fontSize: 12, fontWeight: FontWeight.bold),
                                        ),
                                      ),
                                  ],
                                ),
                                const SizedBox(height: 6),
                                Text(p['details'] ?? '', style: const TextStyle(color: Colors.white70)),
                                const SizedBox(height: 12),
                                Row(
                                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                                  children: [
                                    Column(
                                      crossAxisAlignment: CrossAxisAlignment.start,
                                      children: [
                                        Text(
                                          '${p['price_mmk']} MMK  (\$${p['price_usd']})',
                                          style: const TextStyle(
                                            fontSize: 16,
                                            fontWeight: FontWeight.bold,
                                            color: Color(0xFF14B8A6),
                                          ),
                                        ),
                                        Text(
                                          stock > 0 ? 'In Stock: $stock' : 'Out of Stock',
                                          style: TextStyle(
                                            fontSize: 12,
                                            color: stock > 0 ? Colors.greenAccent : Colors.redAccent,
                                          ),
                                        ),
                                      ],
                                    ),
                                    ElevatedButton.icon(
                                      onPressed: stock > 0 ? () => openCheckoutSheet(p) : null,
                                      style: ElevatedButton.styleFrom(
                                        backgroundColor: const Color(0xFF14B8A6),
                                        foregroundColor: Colors.black,
                                      ),
                                      icon: const Icon(Icons.shopping_cart_checkout, size: 18),
                                      label: Text(stock > 0 ? 'Buy Now' : 'Sold Out'),
                                    ),
                                  ],
                                ),
                              ],
                            ),
                          ),
                        );
                      },
                    ),
                  ),
          ),
        ],
      ),
    );
  }
}

class CheckoutBottomSheet extends StatefulWidget {
  final Map<String, dynamic> item;
  final Map<String, dynamic> storeConfig;
  final VoidCallback onOrderSuccess;

  const CheckoutBottomSheet({
    super.key,
    required this.item,
    required this.storeConfig,
    required this.onOrderSuccess,
  });

  @override
  State<CheckoutBottomSheet> createState() => _CheckoutBottomSheetState();
}

class _CheckoutBottomSheetState extends State<CheckoutBottomSheet> {
  int quantity = 1;
  String paymentMethod = 'KPay';
  final couponCtrl = TextEditingController();
  final targetUserCtrl = TextEditingController();
  final txHashCtrl = TextEditingController();
  bool submitting = false;
  Map<String, dynamic>? createdOrder;

  bool get needsTargetUsername {
    final name = (widget.item['name'] ?? '').toString().toLowerCase();
    return (name.contains('telegram') || name.contains('tg ')) &&
        (name.contains('premium') || name.contains('star'));
  }

  Future<void> placeOrder() async {
    if (needsTargetUsername && targetUserCtrl.text.trim().isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Please enter target Telegram @username')),
      );
      return;
    }

    setState(() => submitting = true);
    final res = await ApiService.createOrder(
      itemId: widget.item['item_id'],
      quantity: quantity,
      paymentMethod: paymentMethod,
      couponCode: couponCtrl.text.trim().isEmpty ? null : couponCtrl.text.trim(),
      targetUsername: targetUserCtrl.text.trim().isEmpty ? null : targetUserCtrl.text.trim(),
    );
    setState(() => submitting = false);

    if (res['ok'] == true) {
      final orderData = res['order'];
      if (orderData['wallet_paid'] == true) {
        Navigator.pop(context);
        widget.onOrderSuccess();
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              orderData['auto_delivered'] == true
                  ? '✅ Paid via Wallet! Product delivered to My Orders.'
                  : '✅ Paid via Wallet! Admin is preparing your delivery.',
            ),
            backgroundColor: Colors.green,
          ),
        );
      } else {
        setState(() => createdOrder = orderData);
      }
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(res['error'] ?? 'Failed'), backgroundColor: Colors.redAccent),
      );
    }
  }

  Future<void> pickAndUploadReceipt() async {
    final picker = ImagePicker();
    final picked = await picker.pickImage(source: ImageSource.gallery);
    if (picked == null) return;

    setState(() => submitting = true);
    final res = await ApiService.uploadPaymentProof(createdOrder!['order_id'], File(picked.path));
    setState(() => submitting = false);

    if (res['ok'] == true) {
      Navigator.pop(context);
      widget.onOrderSuccess();
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(res['message'] ?? 'Submitted!'), backgroundColor: Colors.green),
      );
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(res['error'] ?? 'Upload error'), backgroundColor: Colors.redAccent),
      );
    }
  }

  Future<void> verifyCrypto() async {
    if (txHashCtrl.text.trim().isEmpty) return;
    setState(() => submitting = true);
    String net = 'bep20';
    if (paymentMethod == 'USDT_ERC20') net = 'erc20';
    if (paymentMethod == 'BINANCE_PAY') net = 'binance';

    final res = await ApiService.verifyCryptoPayment(
      orderId: createdOrder!['order_id'],
      network: net,
      txHashOrNote: txHashCtrl.text.trim(),
    );
    setState(() => submitting = false);

    if (res['ok'] == true) {
      Navigator.pop(context);
      widget.onOrderSuccess();
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('✅ Crypto Payment Verified! Check My Orders for your account/key.'),
          backgroundColor: Colors.green,
        ),
      );
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(res['error'] ?? 'Verification failed'), backgroundColor: Colors.redAccent),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final payDetails = (widget.storeConfig['payment_methods'] ?? {}) as Map<String, dynamic>;

    return Padding(
      padding: EdgeInsets.only(
        left: 20,
        right: 20,
        top: 20,
        bottom: MediaQuery.of(context).viewInsets.bottom + 24,
      ),
      child: SingleChildScrollView(
        child: createdOrder == null
            ? Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(widget.item['name'] ?? '', style: const TextStyle(fontSize: 19, fontWeight: FontWeight.bold)),
                  const SizedBox(height: 8),
                  Text(widget.item['description_mm'] ?? '', style: const TextStyle(fontSize: 13, color: Colors.white70)),
                  const Divider(height: 24),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      const Text('Quantity:', style: TextStyle(fontSize: 16)),
                      Row(
                        children: [
                          IconButton(
                            onPressed: quantity > 1 ? () => setState(() => quantity--) : null,
                            icon: const Icon(Icons.remove_circle_outline),
                          ),
                          Text('$quantity', style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                          IconButton(
                            onPressed: quantity < (widget.item['available_stock'] ?? 1)
                                ? () => setState(() => quantity++)
                                : null,
                            icon: const Icon(Icons.add_circle_outline),
                          ),
                        ],
                      ),
                    ],
                  ),
                  if (needsTargetUsername) ...[
                    const SizedBox(height: 10),
                    TextField(
                      controller: targetUserCtrl,
                      decoration: const InputDecoration(
                        labelText: 'Target Telegram @username',
                        hintText: '@yourusername',
                        border: OutlineInputBorder(),
                      ),
                    ),
                  ],
                  const SizedBox(height: 10),
                  DropdownButtonFormField<String>(
                    value: paymentMethod,
                    decoration: const InputDecoration(labelText: 'Payment Method', border: OutlineInputBorder()),
                    items: const [
                      DropdownMenuItem(value: 'KPay', child: Text('KBZPay (MMK Receipt)')),
                      DropdownMenuItem(value: 'WavePay', child: Text('WavePay (MMK Receipt)')),
                      DropdownMenuItem(value: 'Wallet', child: Text('Instant Wallet Balance (Auto-Deliver)')),
                      DropdownMenuItem(value: 'USDT_BEP20', child: Text('USDT (BEP20 Auto-Verify)')),
                      DropdownMenuItem(value: 'USDT_ERC20', child: Text('USDT (ERC20 Auto-Verify)')),
                      DropdownMenuItem(value: 'BINANCE_PAY', child: Text('Binance Pay (Auto-Verify)')),
                    ],
                    onChanged: (v) => setState(() => paymentMethod = v!),
                  ),
                  const SizedBox(height: 10),
                  TextField(
                    controller: couponCtrl,
                    decoration: const InputDecoration(
                      labelText: 'Coupon Code (Optional)',
                      hintText: 'ENI-XXXXXX',
                      border: OutlineInputBorder(),
                    ),
                  ),
                  const SizedBox(height: 18),
                  SizedBox(
                    width: double.infinity,
                    height: 48,
                    child: ElevatedButton(
                      onPressed: submitting ? null : placeOrder,
                      style: ElevatedButton.styleFrom(
                        backgroundColor: const Color(0xFF14B8A6),
                        foregroundColor: Colors.black,
                      ),
                      child: submitting
                          ? const CircularProgressIndicator(color: Colors.black)
                          : const Text('CONFIRM & RESERVE STOCK (10 MIN)', style: TextStyle(fontWeight: FontWeight.bold)),
                    ),
                  ),
                ],
              )
            : Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    'Order Reserved: ${createdOrder!['order_code']}',
                    style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: Color(0xFF14B8A6)),
                  ),
                  const SizedBox(height: 8),
                  Text('Total Payable: ${createdOrder!['total_amount']} MMK (\$${createdOrder!['total_usd']} USDT)'),
                  const SizedBox(height: 12),
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(color: Colors.black26, borderRadius: BorderRadius.circular(10)),
                    child: Row(
                      children: [
                        Expanded(
                          child: SelectableText(
                            'Send to ($paymentMethod):\n${payDetails[paymentMethod] ?? 'Ask Admin'}',
                            style: const TextStyle(fontWeight: FontWeight.bold),
                          ),
                        ),
                        IconButton(
                          icon: const Icon(Icons.copy),
                          onPressed: () {
                            Clipboard.setData(ClipboardData(text: '${payDetails[paymentMethod] ?? ''}'));
                            ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Copied!')));
                          },
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 16),
                  if (paymentMethod == 'KPay' || paymentMethod == 'WavePay')
                    SizedBox(
                      width: double.infinity,
                      height: 48,
                      child: ElevatedButton.icon(
                        onPressed: submitting ? null : pickAndUploadReceipt,
                        icon: const Icon(Icons.upload_file),
                        label: const Text('UPLOAD PAYMENT SCREENSHOT'),
                      ),
                    )
                  else ...[
                    TextField(
                      controller: txHashCtrl,
                      decoration: InputDecoration(
                        labelText: paymentMethod == 'BINANCE_PAY'
                            ? 'Binance Order ID or Note (${createdOrder!['order_code']})'
                            : 'On-Chain Transaction Hash (0x...)',
                        border: const OutlineInputBorder(),
                      ),
                    ),
                    const SizedBox(height: 12),
                    SizedBox(
                      width: double.infinity,
                      height: 48,
                      child: ElevatedButton.icon(
                        onPressed: submitting ? null : verifyCrypto,
                        icon: const Icon(Icons.verified),
                        label: const Text('AUTO-VERIFY CRYPTO & GET KEY'),
                      ),
                    ),
                  ],
                ],
              ),
      ),
    );
  }
}
