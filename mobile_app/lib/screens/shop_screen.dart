import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:image_picker/image_picker.dart';
import '../api_service.dart';
import '../theme.dart';
import '../notifications.dart';

class ShopScreen extends StatefulWidget {
  const ShopScreen({super.key});

  @override
  State<ShopScreen> createState() => _ShopScreenState();
}

class _ShopScreenState extends State<ShopScreen> {
  List<dynamic> products = [];
  Map<String, dynamic> storeConfig = {};
  bool loading = true;
  bool loadFailed = false;
  String searchQuery = '';
  String selectedCategory = 'all';

  @override
  void initState() {
    super.initState();
    loadStore();
  }

  Future<void> loadStore() async {
    setState(() {
      loading = true;
      loadFailed = false;
    });
    try {
      final prods = await ApiService.fetchProducts();
      final cfg = await ApiService.fetchStoreConfig();
      if (!mounted) return;
      setState(() {
        products = prods;
        storeConfig = cfg;
        loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        loading = false;
        loadFailed = true;
      });
    }
  }

  void openCheckoutSheet(Map<String, dynamic> item) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      backgroundColor: AppColors.surface,
      shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(24))),
      builder: (_) => CheckoutBottomSheet(item: item, storeConfig: storeConfig, onOrderSuccess: loadStore),
    );
  }

  int _countFor(String catId) {
    if (catId == 'all') return products.length;
    return products.where((p) => categoryOf('${p['name'] ?? ''}').id == catId).length;
  }

  @override
  Widget build(BuildContext context) {
    final q = searchQuery.trim().toLowerCase();
    final filtered = products.where((p) {
      final name = '${p['name'] ?? ''}';
      if (selectedCategory != 'all' && categoryOf(name).id != selectedCategory) return false;
      if (q.isEmpty) return true;
      return name.toLowerCase().contains(q) || '${p['details'] ?? ''}'.toLowerCase().contains(q);
    }).toList();

    final cats = <StoreCategory>[kAll, ...kCategories, kOther]
        .where((c) => c.id == 'all' || _countFor(c.id) > 0)
        .toList();

    return Scaffold(
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: loadStore,
          child: CustomScrollView(
            physics: const AlwaysScrollableScrollPhysics(),
            slivers: [
              SliverToBoxAdapter(child: _buildHeader()),
              SliverToBoxAdapter(child: _buildSearch()),
              SliverToBoxAdapter(child: _buildCategoryBar(cats)),
              if (loading)
                const SliverFillRemaining(
                  hasScrollBody: false,
                  child: Center(child: CircularProgressIndicator()),
                )
              else if (loadFailed)
                SliverFillRemaining(
                  hasScrollBody: false,
                  child: _EmptyState(
                    icon: Icons.cloud_off_rounded,
                    title: 'Server နဲ့ ချိတ်ဆက်လို့မရပါ',
                    subtitle: 'Internet နဲ့ API URL ကို စစ်ပြီး ပြန်ကြိုးစားပါ။',
                    actionLabel: 'Retry',
                    onAction: loadStore,
                  ),
                )
              else if (filtered.isEmpty)
                const SliverFillRemaining(
                  hasScrollBody: false,
                  child: _EmptyState(
                    icon: Icons.search_off_rounded,
                    title: 'ပစ္စည်း မတွေ့ပါ',
                    subtitle: 'တခြား keyword သို့ category နဲ့ ရှာကြည့်ပါ။',
                  ),
                )
              else
                SliverPadding(
                  padding: const EdgeInsets.fromLTRB(16, 4, 16, 100),
                  sliver: SliverGrid(
                    gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
                      maxCrossAxisExtent: 240,
                      mainAxisExtent: 262,
                      crossAxisSpacing: 12,
                      mainAxisSpacing: 12,
                    ),
                    delegate: SliverChildBuilderDelegate(
                      (context, idx) {
                        final p = Map<String, dynamic>.from(filtered[idx] as Map);
                        return ProductCard(product: p, onBuy: () => openCheckoutSheet(p));
                      },
                      childCount: filtered.length,
                    ),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildHeader() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
      child: Container(
        padding: const EdgeInsets.all(18),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(22),
          gradient: const LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [Color(0xFF0F766E), Color(0xFF155E75), Color(0xFF1E3A8A)],
          ),
        ),
        child: Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                    decoration: BoxDecoration(
                      color: Colors.white.withAlpha(38),
                      borderRadius: BorderRadius.circular(20),
                    ),
                    child: const Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(Icons.verified_rounded, size: 14),
                        SizedBox(width: 4),
                        Text('Trusted Digital Store', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700)),
                      ],
                    ),
                  ),
                  const SizedBox(height: 10),
                  const Text(
                    'ENI Premium Store',
                    style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    'Premium account, VPN, Telegram & Gift Card များကို အလွယ်တကူ ဝယ်ယူပါ',
                    style: TextStyle(fontSize: 12.5, color: Colors.white.withAlpha(215), height: 1.35),
                  ),
                ],
              ),
            ),
            const SizedBox(width: 10),
            Container(
              width: 56,
              height: 56,
              decoration: BoxDecoration(
                color: Colors.white.withAlpha(30),
                borderRadius: BorderRadius.circular(18),
              ),
              child: const Icon(Icons.diamond_rounded, size: 30),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildSearch() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 0, 8, 10),
      child: Row(
        children: [
          Expanded(
            child: TextField(
              onChanged: (val) => setState(() => searchQuery = val),
              decoration: InputDecoration(
                hintText: 'Search VPN, Telegram, Gift Cards...',
                prefixIcon: const Icon(Icons.search_rounded),
                suffixIcon: IconButton(
                  icon: const Icon(Icons.refresh_rounded),
                  tooltip: 'Refresh',
                  onPressed: loadStore,
                ),
                contentPadding: const EdgeInsets.symmetric(vertical: 14),
              ),
            ),
          ),
          const NotificationBell(),
        ],
      ),
    );
  }

  Widget _buildCategoryBar(List<StoreCategory> cats) {
    return SizedBox(
      height: 48,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
        itemCount: cats.length,
        separatorBuilder: (_, __) => const SizedBox(width: 8),
        itemBuilder: (context, i) {
          final c = cats[i];
          final selected = selectedCategory == c.id;
          return GestureDetector(
            onTap: () => setState(() => selectedCategory = c.id),
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 180),
              padding: const EdgeInsets.symmetric(horizontal: 14),
              decoration: BoxDecoration(
                color: selected ? c.color.withAlpha(45) : AppColors.surface,
                borderRadius: BorderRadius.circular(24),
                border: Border.all(color: selected ? c.color : AppColors.border),
              ),
              child: Row(
                children: [
                  Icon(c.icon, size: 17, color: selected ? c.color : AppColors.textDim),
                  const SizedBox(width: 6),
                  Text(
                    c.label,
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w700,
                      color: selected ? AppColors.text : AppColors.textDim,
                    ),
                  ),
                  const SizedBox(width: 6),
                  Text(
                    '${_countFor(c.id)}',
                    style: TextStyle(fontSize: 11, color: selected ? c.color : AppColors.textDim),
                  ),
                ],
              ),
            ),
          );
        },
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;
  final String? actionLabel;
  final VoidCallback? onAction;
  const _EmptyState({
    required this.icon,
    required this.title,
    required this.subtitle,
    this.actionLabel,
    this.onAction,
  });

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 56, color: AppColors.textDim),
            const SizedBox(height: 12),
            Text(title, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
            const SizedBox(height: 6),
            Text(subtitle, textAlign: TextAlign.center, style: TextStyle(color: AppColors.textDim)),
            if (actionLabel != null) ...[
              const SizedBox(height: 14),
              FilledButton.icon(
                onPressed: onAction,
                icon: const Icon(Icons.refresh_rounded),
                label: Text(actionLabel!),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class ProductCard extends StatelessWidget {
  final Map<String, dynamic> product;
  final VoidCallback onBuy;
  const ProductCard({super.key, required this.product, required this.onBuy});

  @override
  Widget build(BuildContext context) {
    final p = product;
    final name = '${p['name'] ?? ''}'.replaceAll('‎', '').trim();
    final int stock = (p['available_stock'] ?? 0) is num ? (p['available_stock'] as num).toInt() : 0;
    final discount = p['discount_percent'];
    final original = p['original_price_mmk'];
    final color = colorForProduct(name);
    final inStock = stock > 0;

    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: AppColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              IconTile(icon: iconForProduct(name), color: color, size: 44),
              if (discount != null)
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
                  decoration: BoxDecoration(
                    color: AppColors.danger,
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    '-${(discount as num).round()}%',
                    style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w800),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 10),
          Text(
            name,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700, height: 1.25),
          ),
          const SizedBox(height: 3),
          Text(
            '${p['details'] ?? ''}',
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(fontSize: 11.5, color: AppColors.textDim, height: 1.3),
          ),
          const Spacer(),
          if (original != null)
            Text(
              '${fmtMoney(original)} Ks',
              style: TextStyle(
                fontSize: 11,
                color: AppColors.textDim,
                decoration: TextDecoration.lineThrough,
              ),
            ),
          Text(
            '${fmtMoney(p['price_mmk'])} Ks',
            style: const TextStyle(fontSize: 16.5, fontWeight: FontWeight.w800, color: AppColors.primary),
          ),
          const SizedBox(height: 2),
          Row(
            children: [
              Icon(Icons.circle, size: 8, color: inStock ? AppColors.ok : AppColors.danger),
              const SizedBox(width: 5),
              Expanded(
                child: Text(
                  inStock ? 'In stock: $stock  •  \$${p['price_usd']}' : 'Out of stock',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: 11, color: inStock ? AppColors.textDim : AppColors.danger),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          SizedBox(
            width: double.infinity,
            height: 36,
            child: FilledButton(
              onPressed: inStock ? onBuy : null,
              style: FilledButton.styleFrom(
                backgroundColor: AppColors.primary,
                foregroundColor: Colors.black,
                padding: EdgeInsets.zero,
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
              ),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(inStock ? Icons.shopping_bag_rounded : Icons.block_rounded, size: 16),
                  const SizedBox(width: 6),
                  Text(inStock ? 'Buy Now' : 'Sold Out', style: const TextStyle(fontWeight: FontWeight.w800)),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _PayMethod {
  final String value;
  final String label;
  final String hint;
  final IconData icon;
  final Color color;
  const _PayMethod(this.value, this.label, this.hint, this.icon, this.color);
}

const List<_PayMethod> _payMethods = [
  _PayMethod('KPay', 'KBZPay', 'Screenshot တင်ပါ', Icons.phone_android_rounded, Color(0xFF2563EB)),
  _PayMethod('WavePay', 'WavePay', 'Screenshot တင်ပါ', Icons.waves_rounded, Color(0xFFFACC15)),
  _PayMethod('Wallet', 'Wallet Balance', 'ချက်ချင်း Auto ပို့ပေး', Icons.account_balance_wallet_rounded, Color(0xFF14B8A6)),
  _PayMethod('USDT_BEP20', 'USDT (BEP20)', 'Auto verify', Icons.currency_bitcoin_rounded, Color(0xFF22C55E)),
  _PayMethod('USDT_ERC20', 'USDT (ERC20)', 'Auto verify', Icons.currency_bitcoin_rounded, Color(0xFFA78BFA)),
  _PayMethod('BINANCE_PAY', 'Binance Pay', 'Auto verify', Icons.payments_rounded, Color(0xFFF59E0B)),
];

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
  String? errorText;
  String? errorCode;

  @override
  void dispose() {
    couponCtrl.dispose();
    targetUserCtrl.dispose();
    txHashCtrl.dispose();
    super.dispose();
  }

  bool get needsTargetUsername {
    final name = (widget.item['name'] ?? '').toString().toLowerCase();
    return (name.contains('telegram') || name.contains('tg ')) &&
        (name.contains('premium') || name.contains('star'));
  }

  num get unitPrice {
    final v = widget.item['price_mmk'];
    return v is num ? v : (num.tryParse('$v') ?? 0);
  }

  void _snack(String msg, {Color? color}) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg), backgroundColor: color));
  }

  void _fail(String msg, {String? code}) {
    setState(() {
      errorText = msg;
      errorCode = code;
    });
  }

  Widget _errorBanner() {
    if (errorText == null) return const SizedBox.shrink();
    final walletShort = errorCode == 'insufficient_wallet';
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppColors.danger.withAlpha(28),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.danger.withAlpha(140)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Icon(Icons.error_outline_rounded, color: AppColors.danger, size: 20),
              const SizedBox(width: 8),
              Expanded(
                child: Text(errorText!, style: const TextStyle(fontSize: 13, height: 1.45)),
              ),
              InkWell(
                onTap: () => setState(() {
                  errorText = null;
                  errorCode = null;
                }),
                child: Icon(Icons.close_rounded, size: 18, color: AppColors.textDim),
              ),
            ],
          ),
          if (walletShort) ...[
            const SizedBox(height: 10),
            Align(
              alignment: Alignment.centerRight,
              child: OutlinedButton.icon(
                onPressed: () => setState(() {
                  paymentMethod = 'KPay';
                  errorText = null;
                  errorCode = null;
                }),
                icon: const Icon(Icons.swap_horiz_rounded, size: 18),
                label: const Text('KBZPay နဲ့ ပြောင်းဝယ်မယ်'),
              ),
            ),
          ],
        ],
      ),
    );
  }

  Future<void> placeOrder() async {
    setState(() {
      errorText = null;
      errorCode = null;
    });
    final target = targetUserCtrl.text.trim();
    if (needsTargetUsername) {
      if (target.isEmpty) {
        _fail('ပို့ပေးရမယ့် Telegram @username ကို ထည့်ပါ။');
        return;
      }
      if (!RegExp(r'^@?[A-Za-z0-9_]{4,32}$').hasMatch(target)) {
        _fail('Telegram @username မမှန်ပါ။ စာလုံး/ဂဏန်း/_ ၄ လုံးမှ ၃၂ လုံးအတွင်း ဖြစ်ရပါမယ်။');
        return;
      }
    }

    setState(() => submitting = true);
    final res = await ApiService.createOrder(
      itemId: widget.item['item_id'],
      quantity: quantity,
      paymentMethod: paymentMethod,
      couponCode: couponCtrl.text.trim().isEmpty ? null : couponCtrl.text.trim(),
      targetUsername: target.isEmpty ? null : target,
    );
    if (!mounted) return;
    setState(() => submitting = false);

    if (res['ok'] == true) {
      final orderData = res['order'];
      if (orderData['wallet_paid'] == true) {
        Navigator.pop(context);
        widget.onOrderSuccess();
        _snack(
          orderData['auto_delivered'] == true
              ? '✅ Wallet နဲ့ ပေးချေပြီးပါပြီ! ပစ္စည်းကို My Orders မှာ ကြည့်ပါ။'
              : '✅ Wallet နဲ့ ပေးချေပြီးပါပြီ! Admin က ပို့ပေးနေပါပြီ၊ ရောက်ရင် အသိပေးပါမယ်။',
          color: Colors.green,
        );
      } else {
        setState(() => createdOrder = orderData);
      }
    } else {
      _fail('${res['error'] ?? 'Order မလုပ်နိုင်ပါ။ ပြန်ကြိုးစားပါ။'}', code: res['code']?.toString());
    }
  }

  Future<void> pickAndUploadReceipt() async {
    setState(() => errorText = null);
    final picker = ImagePicker();
    final picked = await picker.pickImage(source: ImageSource.gallery);
    if (picked == null) return;

    setState(() => submitting = true);
    final res = await ApiService.uploadPaymentProof(createdOrder!['order_id'], File(picked.path));
    if (!mounted) return;
    setState(() => submitting = false);

    if (res['ok'] == true) {
      Navigator.pop(context);
      widget.onOrderSuccess();
      _snack('${res['message'] ?? 'Receipt ပို့ပြီးပါပြီ။'}', color: Colors.green);
    } else {
      _fail('${res['error'] ?? 'Receipt မတင်နိုင်ပါ။ ပြန်ကြိုးစားပါ။'}');
    }
  }

  Future<void> verifyCrypto() async {
    if (txHashCtrl.text.trim().isEmpty) {
      _fail(paymentMethod == 'BINANCE_PAY'
          ? 'Binance Order ID သို့မဟုတ် Note ကို ထည့်ပါ။'
          : 'Transaction Hash (0x...) ကို ထည့်ပါ။');
      return;
    }
    setState(() {
      submitting = true;
      errorText = null;
    });
    String net = 'bep20';
    if (paymentMethod == 'USDT_ERC20') net = 'erc20';
    if (paymentMethod == 'BINANCE_PAY') net = 'binance';

    final res = await ApiService.verifyCryptoPayment(
      orderId: createdOrder!['order_id'],
      network: net,
      txHashOrNote: txHashCtrl.text.trim(),
    );
    if (!mounted) return;
    setState(() => submitting = false);

    if (res['ok'] == true) {
      Navigator.pop(context);
      widget.onOrderSuccess();
      _snack('✅ Payment စစ်ဆေးပြီးပါပြီ! ပစ္စည်းကို My Orders မှာ ကြည့်ပါ။', color: Colors.green);
    } else {
      _fail('${res['error'] ?? 'Payment ကို စစ်ဆေးလို့မရပါ။'}');
    }
  }

  @override
  Widget build(BuildContext context) {
    final payDetails = (widget.storeConfig['payment_methods'] ?? {}) as Map<String, dynamic>;
    final name = '${widget.item['name'] ?? ''}'.replaceAll('‎', '').trim();
    final maxQty = (widget.item['available_stock'] ?? 1) is num ? (widget.item['available_stock'] as num).toInt() : 1;

    return Padding(
      padding: EdgeInsets.only(
        left: 20,
        right: 20,
        top: 4,
        bottom: MediaQuery.of(context).viewInsets.bottom + 24,
      ),
      child: SingleChildScrollView(
        child: createdOrder == null
            ? Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Row(
                    children: [
                      IconTile(icon: iconForProduct(name), color: colorForProduct(name)),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(name, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
                            const SizedBox(height: 2),
                            Text(
                              '${fmtMoney(unitPrice)} Ks',
                              style: const TextStyle(
                                  color: AppColors.primary, fontWeight: FontWeight.w800, fontSize: 15),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                  if ('${widget.item['description_mm'] ?? ''}'.isNotEmpty) ...[
                    const SizedBox(height: 10),
                    Text('${widget.item['description_mm']}',
                        style: TextStyle(fontSize: 12.5, color: AppColors.textDim, height: 1.4)),
                  ],
                  const SizedBox(height: 16),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      const Text('Quantity', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
                      Container(
                        decoration: BoxDecoration(
                          color: AppColors.surfaceHi,
                          borderRadius: BorderRadius.circular(14),
                        ),
                        child: Row(
                          children: [
                            IconButton(
                              onPressed: quantity > 1 ? () => setState(() => quantity--) : null,
                              icon: const Icon(Icons.remove_rounded),
                            ),
                            Text('$quantity', style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
                            IconButton(
                              onPressed: quantity < maxQty ? () => setState(() => quantity++) : null,
                              icon: const Icon(Icons.add_rounded),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                  if (needsTargetUsername) ...[
                    const SizedBox(height: 12),
                    TextField(
                      controller: targetUserCtrl,
                      decoration: const InputDecoration(
                        labelText: 'Target Telegram @username',
                        hintText: '@yourusername',
                        prefixIcon: Icon(Icons.alternate_email_rounded),
                      ),
                    ),
                  ],
                  const SizedBox(height: 16),
                  const Text('Payment Method', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700)),
                  const SizedBox(height: 8),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: _payMethods.map((m) {
                      final sel = paymentMethod == m.value;
                      return GestureDetector(
                        onTap: () => setState(() => paymentMethod = m.value),
                        child: Container(
                          width: (MediaQuery.of(context).size.width - 48) / 2,
                          padding: const EdgeInsets.all(10),
                          decoration: BoxDecoration(
                            color: sel ? m.color.withAlpha(35) : AppColors.surfaceHi,
                            borderRadius: BorderRadius.circular(14),
                            border: Border.all(color: sel ? m.color : AppColors.border, width: sel ? 1.6 : 1),
                          ),
                          child: Row(
                            children: [
                              Icon(m.icon, color: m.color, size: 22),
                              const SizedBox(width: 8),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(m.label,
                                        maxLines: 1,
                                        overflow: TextOverflow.ellipsis,
                                        style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700)),
                                    Text(m.hint,
                                        maxLines: 1,
                                        overflow: TextOverflow.ellipsis,
                                        style: TextStyle(fontSize: 10.5, color: AppColors.textDim)),
                                  ],
                                ),
                              ),
                            ],
                          ),
                        ),
                      );
                    }).toList(),
                  ),
                  const SizedBox(height: 14),
                  TextField(
                    controller: couponCtrl,
                    decoration: const InputDecoration(
                      labelText: 'Coupon Code (Optional)',
                      hintText: 'ENI-XXXXXX',
                      prefixIcon: Icon(Icons.local_offer_outlined),
                    ),
                  ),
                  const SizedBox(height: 18),
                  _errorBanner(),
                  SizedBox(
                    width: double.infinity,
                    height: 50,
                    child: FilledButton(
                      onPressed: submitting ? null : placeOrder,
                      style: FilledButton.styleFrom(
                        backgroundColor: AppColors.primary,
                        foregroundColor: Colors.black,
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                      ),
                      child: submitting
                          ? const SizedBox(
                              width: 22,
                              height: 22,
                              child: CircularProgressIndicator(color: Colors.black, strokeWidth: 2.5),
                            )
                          : Text(
                              'Confirm Order  •  ${fmtMoney(unitPrice * quantity)} Ks',
                              style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 15),
                            ),
                    ),
                  ),
                  const SizedBox(height: 6),
                  Center(
                    child: Text('Stock ကို ၁၀ မိနစ် reserve လုပ်ပေးထားပါမယ်',
                        style: TextStyle(fontSize: 11, color: AppColors.textDim)),
                  ),
                ],
              )
            : Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Row(
                    children: [
                      const Icon(Icons.check_circle_rounded, color: AppColors.ok, size: 28),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Text(
                          'Order Reserved: ${createdOrder!['order_code']}',
                          style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 10),
                  SectionCard(
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Text('Total Payable', style: TextStyle(color: AppColors.textDim)),
                        Text(
                          '${fmtMoney(createdOrder!['total_amount'])} Ks  (\$${createdOrder!['total_usd']})',
                          style: const TextStyle(fontWeight: FontWeight.w800, color: AppColors.primary),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 10),
                  SectionCard(
                    child: Row(
                      children: [
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text('Send to ($paymentMethod)',
                                  style: TextStyle(fontSize: 12, color: AppColors.textDim)),
                              const SizedBox(height: 4),
                              SelectableText(
                                '${payDetails[paymentMethod] ?? 'Ask Admin'}',
                                style: const TextStyle(fontWeight: FontWeight.w700),
                              ),
                            ],
                          ),
                        ),
                        IconButton(
                          icon: const Icon(Icons.copy_rounded),
                          onPressed: () {
                            Clipboard.setData(ClipboardData(text: '${payDetails[paymentMethod] ?? ''}'));
                            _snack('Copied!');
                          },
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 16),
                  _errorBanner(),
                  if (paymentMethod == 'KPay' || paymentMethod == 'WavePay')
                    SizedBox(
                      width: double.infinity,
                      height: 50,
                      child: FilledButton.icon(
                        onPressed: submitting ? null : pickAndUploadReceipt,
                        icon: const Icon(Icons.upload_file_rounded),
                        label: const Text('Upload Payment Screenshot'),
                        style: FilledButton.styleFrom(
                          backgroundColor: AppColors.primary,
                          foregroundColor: Colors.black,
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                        ),
                      ),
                    )
                  else ...[
                    TextField(
                      controller: txHashCtrl,
                      decoration: InputDecoration(
                        labelText: paymentMethod == 'BINANCE_PAY'
                            ? 'Binance Order ID or Note (${createdOrder!['order_code']})'
                            : 'On-Chain Transaction Hash (0x...)',
                      ),
                    ),
                    const SizedBox(height: 12),
                    SizedBox(
                      width: double.infinity,
                      height: 50,
                      child: FilledButton.icon(
                        onPressed: submitting ? null : verifyCrypto,
                        icon: const Icon(Icons.verified_rounded),
                        label: const Text('Auto-Verify & Get Key'),
                        style: FilledButton.styleFrom(
                          backgroundColor: AppColors.primary,
                          foregroundColor: Colors.black,
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                        ),
                      ),
                    ),
                  ],
                ],
              ),
      ),
    );
  }
}