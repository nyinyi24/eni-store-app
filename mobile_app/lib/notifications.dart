import 'dart:async';
import 'package:flutter/material.dart';
import 'api_service.dart';
import 'theme.dart';

class AppNotification {
  final int id;
  final String kind;
  final String title;
  final String body;
  final int? orderId;
  final bool isRead;
  final String createdAt;
  const AppNotification({
    required this.id,
    required this.kind,
    required this.title,
    required this.body,
    required this.orderId,
    required this.isRead,
    required this.createdAt,
  });

  factory AppNotification.fromJson(Map<String, dynamic> j) => AppNotification(
        id: (j['id'] as num).toInt(),
        kind: '${j['kind'] ?? ''}',
        title: '${j['title'] ?? ''}',
        body: '${j['body'] ?? ''}',
        orderId: j['order_id'] is num ? (j['order_id'] as num).toInt() : null,
        isRead: j['is_read'] == true,
        createdAt: '${j['created_at'] ?? ''}',
      );
}

/// Polls the server while the app is open and keeps an unread counter.
/// (True background push needs Firebase; this works whenever the app is running.)
class NotificationService extends ChangeNotifier {
  NotificationService._();
  static final NotificationService instance = NotificationService._();

  Timer? _timer;
  int _maxSeenId = -1; // -1 = first poll not done yet
  List<AppNotification> items = [];
  int unread = 0;

  /// Bumped whenever new notifications arrive, so screens can reload their data.
  final ValueNotifier<int> dataTick = ValueNotifier<int>(0);

  /// Called with the NEW (unseen) notifications from the latest poll.
  void Function(List<AppNotification> fresh)? onFresh;

  void start() {
    stop();
    _maxSeenId = -1;
    poll();
    _timer = Timer.periodic(const Duration(seconds: 20), (_) => poll());
  }

  void stop() {
    _timer?.cancel();
    _timer = null;
    items = [];
    unread = 0;
    _maxSeenId = -1;
  }

  Future<void> poll() async {
    final res = await ApiService.fetchNotifications();
    if (res['ok'] != true) return;
    final data = Map<String, dynamic>.from(res['data'] as Map);
    final list = (data['notifications'] as List? ?? [])
        .map((e) => AppNotification.fromJson(Map<String, dynamic>.from(e as Map)))
        .toList();
    final firstPoll = _maxSeenId == -1;
    final fresh = list.where((n) => n.id > _maxSeenId && !n.isRead).toList();
    for (final n in list) {
      if (n.id > _maxSeenId) _maxSeenId = n.id;
    }
    if (_maxSeenId < 0) _maxSeenId = 0;
    items = list;
    unread = (data['unread'] as num?)?.toInt() ?? 0;
    notifyListeners();
    if (fresh.isNotEmpty) {
      dataTick.value++;
      // On app start only announce if something is waiting, as a single summary.
      onFresh?.call(firstPoll ? [fresh.first] : fresh);
    }
  }

  Future<void> markAllRead() async {
    await ApiService.markNotificationsRead();
    items = items
        .map((n) => AppNotification(
              id: n.id,
              kind: n.kind,
              title: n.title,
              body: n.body,
              orderId: n.orderId,
              isRead: true,
              createdAt: n.createdAt,
            ))
        .toList();
    unread = 0;
    notifyListeners();
  }
}

IconData _iconForKind(String kind) {
  switch (kind) {
    case 'order_success':
      return Icons.check_circle_rounded;
    case 'order_partial':
      return Icons.inventory_rounded;
    case 'order_rejected':
    case 'topup_rejected':
      return Icons.cancel_rounded;
    case 'topup_approved':
      return Icons.account_balance_wallet_rounded;
    default:
      return Icons.notifications_rounded;
  }
}

Color _colorForKind(String kind) {
  switch (kind) {
    case 'order_success':
    case 'topup_approved':
      return AppColors.ok;
    case 'order_partial':
      return AppColors.warn;
    case 'order_rejected':
    case 'topup_rejected':
      return AppColors.danger;
    default:
      return AppColors.accent;
  }
}

class NotificationBell extends StatelessWidget {
  const NotificationBell({super.key});

  @override
  Widget build(BuildContext context) {
    final svc = NotificationService.instance;
    return ListenableBuilder(
      listenable: svc,
      builder: (context, _) => IconButton(
        tooltip: 'Notifications',
        onPressed: () => showNotificationsSheet(context),
        icon: Stack(
          clipBehavior: Clip.none,
          children: [
            const Icon(Icons.notifications_none_rounded),
            if (svc.unread > 0)
              Positioned(
                right: -4,
                top: -4,
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
                  decoration: BoxDecoration(
                    color: AppColors.danger,
                    borderRadius: BorderRadius.circular(10),
                  ),
                  constraints: const BoxConstraints(minWidth: 16),
                  child: Text(
                    svc.unread > 9 ? '9+' : '${svc.unread}',
                    textAlign: TextAlign.center,
                    style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w800, color: Colors.white),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

Future<void> showNotificationsSheet(BuildContext context) async {
  final svc = NotificationService.instance;
  await svc.poll();
  if (!context.mounted) return;
  await showModalBottomSheet(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    backgroundColor: AppColors.surface,
    shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(24))),
    builder: (ctx) => DraggableScrollableSheet(
      expand: false,
      initialChildSize: 0.65,
      minChildSize: 0.4,
      maxChildSize: 0.92,
      builder: (ctx, scroll) => ListenableBuilder(
        listenable: svc,
        builder: (ctx, _) => Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 12, 8),
              child: Row(
                children: [
                  const Expanded(
                    child: Text('Notifications', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
                  ),
                  if (svc.unread > 0)
                    TextButton(onPressed: svc.markAllRead, child: const Text('အားလုံး ဖတ်ပြီး')),
                ],
              ),
            ),
            Expanded(
              child: svc.items.isEmpty
                  ? Center(
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(Icons.notifications_off_outlined, size: 48, color: AppColors.textDim),
                          const SizedBox(height: 8),
                          Text('အသိပေးချက် မရှိသေးပါ', style: TextStyle(color: AppColors.textDim)),
                        ],
                      ),
                    )
                  : ListView.separated(
                      controller: scroll,
                      padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
                      itemCount: svc.items.length,
                      separatorBuilder: (_, __) => const SizedBox(height: 8),
                      itemBuilder: (ctx, i) {
                        final n = svc.items[i];
                        final color = _colorForKind(n.kind);
                        return Container(
                          padding: const EdgeInsets.all(12),
                          decoration: BoxDecoration(
                            color: n.isRead ? AppColors.surface : color.withAlpha(22),
                            borderRadius: BorderRadius.circular(14),
                            border: Border.all(color: n.isRead ? AppColors.border : color.withAlpha(120)),
                          ),
                          child: Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Icon(_iconForKind(n.kind), color: color),
                              const SizedBox(width: 10),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(n.title, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 14)),
                                    const SizedBox(height: 3),
                                    Text(n.body,
                                        style: TextStyle(fontSize: 12.5, color: AppColors.textDim, height: 1.35)),
                                    const SizedBox(height: 5),
                                    Text(n.createdAt, style: TextStyle(fontSize: 10.5, color: AppColors.textDim)),
                                  ],
                                ),
                              ),
                            ],
                          ),
                        );
                      },
                    ),
            ),
          ],
        ),
      ),
    ),
  );
  // Opening the list counts as reading it.
  if (svc.unread > 0) {
    await svc.markAllRead();
  }
}