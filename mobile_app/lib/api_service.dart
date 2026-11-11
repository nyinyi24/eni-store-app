import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

class ApiService {
  // Change this via "--dart-define=API_BASE_URL=https://your-domain.com/api" in GitHub Actions
  // or edit defaultUrl directly below:
  static const String defaultUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://13.228.96.27:8000/api',
  );

  static Future<String> getBaseUrl() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString('custom_api_url') ?? defaultUrl;
  }

  static Future<void> setCustomBaseUrl(String url) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('custom_api_url', url.trim());
  }

  static Future<String?> getToken() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString('jwt_token');
  }

  static Future<void> logout() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('jwt_token');
  }

  static Future<Map<String, dynamic>> login(String phoneOrEmail, String password) async {
    final baseUrl = await getBaseUrl();
    final res = await http.post(
      Uri.parse('$baseUrl/auth/login'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'phone_or_email': phoneOrEmail,
        'password': password,
      }),
    );
    final data = jsonDecode(res.body);
    if (res.statusCode == 200 && data['token'] != null) {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('jwt_token', data['token']);
      return {'ok': true, 'data': data};
    }
    return {'ok': false, 'error': data['detail'] ?? 'Login failed'};
  }

  static Future<Map<String, dynamic>> register({
    required String fullName,
    required String phoneOrEmail,
    required String password,
    int? telegramUserId,
  }) async {
    final baseUrl = await getBaseUrl();
    final res = await http.post(
      Uri.parse('$baseUrl/auth/register'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'full_name': fullName,
        'phone_or_email': phoneOrEmail,
        'password': password,
        'telegram_user_id': telegramUserId,
      }),
    );
    final data = jsonDecode(res.body);
    if (res.statusCode == 200 && data['token'] != null) {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('jwt_token', data['token']);
      return {'ok': true, 'data': data};
    }
    return {'ok': false, 'error': data['detail'] ?? 'Registration failed'};
  }

  static Future<Map<String, dynamic>> fetchStoreConfig() async {
    final baseUrl = await getBaseUrl();
    final res = await http.get(Uri.parse('$baseUrl/store/config'));
    if (res.statusCode == 200) {
      return jsonDecode(res.body);
    }
    return {};
  }

  static Future<List<dynamic>> fetchProducts() async {
    final baseUrl = await getBaseUrl();
    final res = await http.get(Uri.parse('$baseUrl/products'));
    if (res.statusCode == 200) {
      return jsonDecode(res.body)['products'] ?? [];
    }
    throw Exception('Failed to load products');
  }

  static Future<Map<String, dynamic>> checkCoupon(String code, double totalAmount) async {
    final baseUrl = await getBaseUrl();
    final token = await getToken();
    final res = await http.post(
      Uri.parse('$baseUrl/coupons/check'),
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer $token',
      },
      body: jsonEncode({'code': code, 'total_amount': totalAmount}),
    );
    final data = jsonDecode(res.body);
    if (res.statusCode == 200) {
      return {'ok': true, 'coupon': data['coupon']};
    }
    return {'ok': false, 'error': data['detail'] ?? 'Invalid coupon'};
  }

  static Future<Map<String, dynamic>> createOrder({
    required int itemId,
    required int quantity,
    required String paymentMethod,
    String? couponCode,
    String? targetUsername,
  }) async {
    final baseUrl = await getBaseUrl();
    final token = await getToken();
    final res = await http.post(
      Uri.parse('$baseUrl/orders'),
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer $token',
      },
      body: jsonEncode({
        'item_id': itemId,
        'quantity': quantity,
        'payment_method': paymentMethod,
        'coupon_code': couponCode,
        'target_username': targetUsername,
      }),
    );
    final data = jsonDecode(res.body);
    if (res.statusCode == 200) {
      return {'ok': true, 'order': data};
    }
    return {'ok': false, 'error': data['detail'] ?? 'Order creation failed'};
  }

  static Future<Map<String, dynamic>> uploadPaymentProof(int orderId, File imageFile) async {
    final baseUrl = await getBaseUrl();
    final token = await getToken();
    final req = http.MultipartRequest('POST', Uri.parse('$baseUrl/orders/$orderId/proof'));
    req.headers['Authorization'] = 'Bearer $token';
    req.files.add(await http.MultipartFile.fromPath('file', imageFile.path));
    final streamed = await req.send();
    final body = await streamed.stream.bytesToString();
    final data = jsonDecode(body);
    if (streamed.statusCode == 200) {
      return {'ok': true, 'message': data['message']};
    }
    return {'ok': false, 'error': data['detail'] ?? 'Upload failed'};
  }

  static Future<Map<String, dynamic>> verifyCryptoPayment({
    required int orderId,
    required String network,
    required String txHashOrNote,
  }) async {
    final baseUrl = await getBaseUrl();
    final token = await getToken();
    final res = await http.post(
      Uri.parse('$baseUrl/orders/verify-crypto'),
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer $token',
      },
      body: jsonEncode({
        'order_id': orderId,
        'network': network,
        'tx_hash_or_note': txHashOrNote,
      }),
    );
    final data = jsonDecode(res.body);
    if (res.statusCode == 200) {
      return {'ok': true, 'data': data};
    }
    return {'ok': false, 'error': data['detail'] ?? 'Verification failed'};
  }

  static Future<Map<String, dynamic>> fetchDashboard() async {
    final baseUrl = await getBaseUrl();
    final token = await getToken();
    final res = await http.get(
      Uri.parse('$baseUrl/user/dashboard'),
      headers: {'Authorization': 'Bearer $token'},
    );
    if (res.statusCode == 200) {
      return jsonDecode(res.body);
    }
    throw Exception('Session expired');
  }

  static Future<Map<String, dynamic>> claimDailyCheckin() async {
    final baseUrl = await getBaseUrl();
    final token = await getToken();
    final res = await http.post(
      Uri.parse('$baseUrl/wallet/checkin'),
      headers: {'Authorization': 'Bearer $token'},
    );
    final data = jsonDecode(res.body);
    if (res.statusCode == 200) {
      return {'ok': true, 'data': data};
    }
    return {'ok': false, 'error': data['detail'] ?? 'Already checked in'};
  }

  static Future<Map<String, dynamic>> redeemPoints() async {
    final baseUrl = await getBaseUrl();
    final token = await getToken();
    final res = await http.post(
      Uri.parse('$baseUrl/wallet/redeem'),
      headers: {'Authorization': 'Bearer $token'},
    );
    final data = jsonDecode(res.body);
    if (res.statusCode == 200) {
      return {'ok': true, 'data': data};
    }
    return {'ok': false, 'error': data['detail'] ?? 'Not enough points'};
  }

  static Future<Map<String, dynamic>> uploadWalletTopup({
    required double amount,
    required String method,
    required File imageFile,
  }) async {
    final baseUrl = await getBaseUrl();
    final token = await getToken();
    final req = http.MultipartRequest(
      'POST',
      Uri.parse('$baseUrl/wallet/topup?amount=$amount&payment_method=$method'),
    );
    req.headers['Authorization'] = 'Bearer $token';
    req.files.add(await http.MultipartFile.fromPath('file', imageFile.path));
    final streamed = await req.send();
    final body = await streamed.stream.bytesToString();
    final data = jsonDecode(body);
    if (streamed.statusCode == 200) {
      return {'ok': true, 'message': data['message']};
    }
    return {'ok': false, 'error': data['detail'] ?? 'Top-up failed'};
  }
}
