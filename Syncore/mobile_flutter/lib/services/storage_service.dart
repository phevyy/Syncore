import 'dart:convert';
import 'package:shared_preferences/shared_preferences.dart';

/// Kullanıcı kimlik bilgilerini ve bağlantı bilgilerini cihazda saklar.
class StorageService {
  static const _keyUsername  = 'username';
  static const _keyPwdHash   = 'password_sha256_b64'; // base64(SHA-256(password))
  static const _keyServerIp  = 'server_ip';
  static const _keyCache     = 'cached_passwords';

  /// Kayıt / giriş sonrası kimlik bilgilerini kaydet.
  static Future<void> saveCredentials(String username, String passwordSha256B64) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_keyUsername, username);
    await prefs.setString(_keyPwdHash, passwordSha256B64);
  }

  /// QR tarama veya manuel giriş sonrası sunucu IP'sini kaydet.
  static Future<void> saveServerIp(String ip) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_keyServerIp, ip);
  }

  /// Kayıtlı kimlik + bağlantı bilgilerini yükle. Kimlik yoksa null döner.
  static Future<({String username, String passwordSha256B64, String? serverIp})?> load() async {
    final prefs = await SharedPreferences.getInstance();
    final username = prefs.getString(_keyUsername);
    final pwdHash  = prefs.getString(_keyPwdHash);
    if (username == null || pwdHash == null) return null;
    return (
      username: username,
      passwordSha256B64: pwdHash,
      serverIp: prefs.getString(_keyServerIp),
    );
  }

  /// Sadece kayıtlı kimlik bilgisi var mı kontrol eder.
  static Future<bool> hasCredentials() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.containsKey(_keyUsername) && prefs.containsKey(_keyPwdHash);
  }

  /// Şifre listesini önbelleğe yazar (çevrimdışı gösterim için).
  static Future<void> savePasswordCache(List<Map<String, dynamic>> entries) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_keyCache, jsonEncode(entries));
  }

  /// Önbellekteki şifre listesini yükler. Yoksa null döner.
  static Future<List<Map<String, dynamic>>?> loadPasswordCache() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_keyCache);
    if (raw == null) return null;
    return (jsonDecode(raw) as List)
        .map((e) => Map<String, dynamic>.from(e as Map))
        .toList();
  }

  /// Sadece sunucu IP'sini sil (oturum sonrası veya QR tarama öncesi).
  static Future<void> clearServerIp() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_keyServerIp);
  }

  /// Tüm kayıtlı verileri sil.
  static Future<void> clear() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_keyUsername);
    await prefs.remove(_keyPwdHash);
    await prefs.remove(_keyServerIp);
    await prefs.remove(_keyCache);
  }
}
