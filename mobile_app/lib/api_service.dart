import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

class ApiService {
  static const String defaultUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://13.228.96.27:8000/api',
  );

  static Future<String> getBaseUrl() async {
    final prefs = await SharedPreferences.getInstance();
    final url = prefs.getString('custom_api_url') ?? defaultUrl;
    return url.endsWith('/') ? url.substring(0, url.length - 1) : url;
  }

  static Future<void> setCustomBaseUrl(String url) async {
    final prefs = await SharedPreferences.getInstance();
    String clean = url.trim();
    if (clean.endsWith('/')) {
      clean = clean.substring(0, clean.length - 1);
    }
    await prefs.setString('custom_api_url', clean);
  }

  static Future<String?> getToken() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString('jwt_token');
  }

  static Future<void> logout() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('jwt_token');
  }

  static Map<String, dynamic> _safeDecode(http.Response res) {
    try {
      final decoded = jsonDecode(utf8.decode(res.bodyBytes));
      if (decoded is Map<String, dynamic>) return decoded;
      return {'detail': res.body};
    } catch (_) {
      return {'detail': 'Server returned HTTP ${res.statusCode}'};
    }
  }

  static Future> login(String phoneOrEmail, String password) async {
    if (phoneOrEmail.length < 4 || password.length < 4) {
      return {'ok': false, 'error': 'Username/Phone နှင့် Password သည် အနည်းဆုံး ၄ လုံး ရှိရပါမည်။'};
    }
    try {
      final baseUrl = await getBaseUrl();
      final res = await http
          .post(
            Uri.parse('$baseUrl/auth/login'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({
              'phone_or_email': phoneOrEmail,
              'password': password,
            }),
          )
          .timeout(const Duration(seconds: 15));

      final data = _safeDecode(res);
      if (res.statusCode == 200 && data['token'] != null) {
        final prefs = await SharedPreferences.getInstance();
        await prefs.setString('jwt_token', data['token']);
        return {'ok': true, 'data': data};
      }
      return {'ok': false, 'error': data['detail'] ?? 'Login failed (HTTP ${res.statusCode})'};
    } on TimeoutException {
      return {'ok': false, 'error': 'Server ချိတ်ဆက်ချိန် ကုန်ဆုံးသွားပါသည်။ (Port 8000 စစ်ဆေးပါ)'};
    } on SocketException catch (e) {
      return {'ok': false, 'error': 'Server သို့ ချိတ်ဆက်၍မရပါ (${e.message})။ API URL စစ်ပါ။'};
    } catch (e) {
      return {'ok': false, 'error': 'Connection Error: $e'};
    }
  }

  static Future> register({
    required String fullName,
    required String phoneOrEmail,
    required String password,
    int? telegramUserId,
  }) async {
    if (phoneOrEmail.length < 4 || password.length < 4) {
      return {'ok': false, 'error': 'Username/Phone နှင့် Password သည် အနည်းဆုံး ၄ လုံး ရှိရပါမည်။'};
    }
    try {
      final baseUrl = await getBaseUrl();
      final res = await http
          .post(
            Uri.parse('$baseUrl/auth/register'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({
              'full_name': fullName,
              'phone_or_email': phoneOrEmail,
              'password': password,
              'telegram_user_id': telegramUserId,
            }),
          )
          .timeout(const Duration(seconds: 15));

      final data = _safeDecode(res);
      if (res.statusCode == 200 && data['token'] != null) {
        final prefs = await SharedPreferences.getInstance();
        await prefs.setString('jwt_token', data['token']);
        return {'ok': true, 'data': data};
      }
      return {'ok': false, 'error': data['detail'] ?? 'Registration failed (HTTP ${res.statusCode})'};
    } on TimeoutException {
      return {'ok': false, 'error': 'Server ချိတ်ဆက်ချိန် ကုန်ဆုံးသွားပါသည်။ (Port 8000 စစ်ဆေးပါ)'};
    } on SocketException catch (e) {
      return {'ok': false, 'error': 'Server သို့ ချိတ်ဆက်၍မရပါ (${e.message})။ API URL စစ်ပါ။'};
    } catch (e) {
      return {'ok': false, 'error': 'Connection Error: $e'};
    }
  }

  static Future> fetchStoreConfig() async {
    try {
      final baseUrl = await getBaseUrl();
      final res = await http.get(Uri.parse('$baseUrl/store/config')).timeout(const Duration(seconds: 15));
      if (res.statusCode == 200) {
        return _safeDecode(res);
      }
    } catch (_) {}
    return {};
  }

  static Future<List<dynamic>> fetchProducts() async {
    final baseUrl = await getBaseUrl();
    final res = await http.get(Uri.parse('$baseUrl/products')).timeout(const Duration(seconds: 15));
    if (res.statusCode == 200) {
      return _safeDecode(res)['products'] ?? [];
    }
    throw Exception('Failed to load products');
  }

  static Future> checkCoupon(String code, double totalAmount) async {
    try {
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
      final data = _safeDecode(res);
      if (res.statusCode == 200) {
        return {'ok': true, 'coupon': data['coupon']};
      }
      return {'ok': false, 'error': data['detail'] ?? 'Invalid coupon'};
    } catch (e) {
      return {'ok': false, 'error': 'Network error: $e'};
    }
  }

  static Future> createOrder({
    required int itemId,
    required int quantity,
    required String paymentMethod,
    String? couponCode,
    String? targetUsername,
  }) async {
    try {
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
      final data = _safeDecode(res);
      if (res.statusCode == 200) {
        return {'ok': true, 'order': data};
      }
      return {'ok': false, 'error': data['detail'] ?? 'Order creation failed'};
    } catch (e) {
      return {'ok': false, 'error': 'Network error: $e'};
    }
  }

  static Future> uploadPaymentProof(int orderId, File imageFile) async {
    try {
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
    } catch (e) {
      return {'ok': false, 'error': 'Upload error: $e'};
    }
  }

  static Future> verifyCryptoPayment({
    required int orderId,
    required String network,
    required String txHashOrNote,
  }) async {
    try {
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
      final data = _safeDecode(res);
      if (res.statusCode == 200) {
        return {'ok': true, 'data': data};
      }
      return {'ok': false, 'error': data['detail'] ?? 'Verification failed'};
    } catch (e) {
      return {'ok': false, 'error': 'Verification error: $e'};
    }
  }

  static Future> fetchDashboard() async {
    final baseUrl = await getBaseUrl();
    final token = await getToken();
    final res = await http.get(
      Uri.parse('$baseUrl/user/dashboard'),
      headers: {'Authorization': 'Bearer $token'},
    );
    if (res.statusCode == 200) {
      return _safeDecode(res);
    }
    throw Exception('Session expired');
  }

  static Future> claimDailyCheckin() async {
    try {
      final baseUrl = await getBaseUrl();
      final token = await getToken();
      final res = await http.post(
        Uri.parse('$baseUrl/wallet/checkin'),
        headers: {'Authorization': 'Bearer $token'},
      );
      final data = _safeDecode(res);
      if (res.statusCode == 200) {
        return {'ok': true, 'data': data};
      }
      return {'ok': false, 'error': data['detail'] ?? 'Already checked in'};
    } catch (e) {
      return {'ok': false, 'error': 'Network error: $e'};
    }
  }

  static Future> redeemPoints() async {
    try {
      final baseUrl = await getBaseUrl();
      final token = await getToken();
      final res = await http.post(
        Uri.parse('$baseUrl/wallet/redeem'),
        headers: {'Authorization': 'Bearer $token'},
      );
      final data = _safeDecode(res);
      if (res.statusCode == 200) {
        return {'ok': true, 'data': data};
      }
      return {'ok': false, 'error': data['detail'] ?? 'Not enough points'};
    } catch (e) {
      return {'ok': false, 'error': 'Network error: $e'};
    }
  }

  static Future> uploadWalletTopup({
    required double amount,
    required String method,
    required File imageFile,
  }) async {
    try {
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
    } catch (e) {
      return {'ok': false, 'error': 'Upload error: $e'};
    }
  }
}