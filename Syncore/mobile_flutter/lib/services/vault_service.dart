import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'package:crypto/crypto.dart';

/// Desktop vault API ile kalıcı TCP oturumu.
/// Auth → CRUD session akışını yönetir.
class VaultSession {
  static const _port    = 8765;
  static const _timeout = Duration(seconds: 15);

  final Socket     _socket;
  final _ByteReader _reader;
  bool _closed = false;
  // Tek seferde sadece bir istek: concurrent _req çağrılarını sıraya koyar
  Future<void> _pending = Future.value();

  VaultSession._(this._socket, this._reader);

  /// Bağlan, auth yap ve session döndür. Başarısızlıkta exception fırlatır.
  static Future<VaultSession> connect({
    required String serverIp,
    required String username,
    required String passwordSha256B64,
  }) async {
    final socket = await Socket.connect(serverIp, _port, timeout: _timeout);
    socket.setOption(SocketOption.tcpNoDelay, true);
    final reader = _ByteReader(socket);

    // auth_request — password_hash ile birlikte gönder (TOFU / mobile-first için)
    _sendMsg(socket, {
      'type': 'auth_request',
      'device_id': 1,
      'username': username,
      'password_hash': passwordSha256B64,
    });

    // challenge al
    final chMsg = await reader.recvMsg().timeout(_timeout);
    if (chMsg['type'] != 'challenge') {
      socket.destroy();
      throw Exception('Beklenmedik yanıt: ${chMsg['type']}');
    }

    // HMAC hesapla
    final key       = base64.decode(passwordSha256B64);
    final challenge = base64.decode(chMsg['challenge'] as String);
    final digest    = Hmac(sha256, key).convert(challenge);
    _sendMsg(socket, {
      'type': 'response',
      'response': base64.encode(digest.bytes),
      'device_id': 1,
    });

    // sonuç
    final result = await reader.recvMsg().timeout(_timeout);
    if (result['type'] != 'success') {
      socket.destroy();
      throw Exception(result['message'] ?? 'Auth başarısız');
    }

    return VaultSession._(socket, reader);
  }

  // ── İstek / Yanıt ────────────────────────────────────────────────────

  Future<Map<String, dynamic>> _req(Map<String, dynamic> msg) async {
    final prev = _pending;
    final completer = Completer<void>();
    _pending = completer.future;
    try {
      await prev; // önceki istek bitsin — hata verse bile finally çalışır
      if (_closed) throw Exception('Oturum kapalı');
      _sendMsg(_socket, msg);
      return await _reader.recvMsg().timeout(_timeout);
    } finally {
      completer.complete();
    }
  }

  _ByteReader get reader => _reader;

  // ── Şifre Listesi ────────────────────────────────────────────────────

  Future<List<Map<String, dynamic>>> listPasswords({
    bool favoritesOnly = false,
    bool trashedOnly   = false,
  }) async {
    final resp    = await _req({
      'type': 'list_passwords',
      'favorites_only': favoritesOnly,
      'trashed_only':   trashedOnly,
    });
    final rawList = resp['entries'] as List<dynamic>;
    return rawList
        .map((e) => Map<String, dynamic>.from(e as Map))
        .toList();
  }

  /// Desktop'tan gelen anlık veri değişikliklerini sorgular.
  /// true dönerse liste yenilenmeli.
  Future<bool> pollEvents() async {
    try {
      final resp = await _req({'type': 'poll_events'});
      return resp['data_changed'] as bool? ?? false;
    } catch (_) {
      return false;
    }
  }

  Future<String> getPassword(int id) async {
    final resp = await _req({'type': 'get_password', 'id': id});
    return resp['password'] as String? ?? '';
  }

  // ── CRUD ─────────────────────────────────────────────────────────────

  Future<int> addPassword({
    required String title,
    required String username,
    required String password,
    String url   = '',
    String notes = '',
    String? uuid,
  }) async {
    final msg = <String, dynamic>{
      'type':     'add_password',
      'title':    title,
      'username': username,
      'password': password,
      'url':      url,
      'notes':    notes,
    };
    if (uuid != null) msg['uuid'] = uuid;
    final resp = await _req(msg);
    if (resp['type'] == 'error') throw Exception(resp['message']);
    return (resp['id'] as num?)?.toInt() ?? 0;
  }

  Future<void> updatePassword(
    int id, {
    String? title,
    String? username,
    String? password,
    String? url,
    String? notes,
  }) async {
    final msg = <String, dynamic>{'type': 'update_password', 'id': id};
    if (title    != null) msg['title']    = title;
    if (username != null) msg['username'] = username;
    if (password != null) msg['password'] = password;
    if (url      != null) msg['url']      = url;
    if (notes    != null) msg['notes']    = notes;
    final resp = await _req(msg);
    if (resp['type'] == 'error') throw Exception(resp['message']);
  }

  Future<void> trashPassword(int id)   async => _checkOk(await _req({'type': 'trash_password',   'id': id}));
  Future<void> restorePassword(int id) async => _checkOk(await _req({'type': 'restore_password', 'id': id}));
  Future<void> deletePassword(int id)  async => _checkOk(await _req({'type': 'delete_password',  'id': id}));
  Future<void> toggleFavorite(int id)  async => _checkOk(await _req({'type': 'toggle_favorite',  'id': id}));

  /// Yerel şifreleri ve silinmiş UUID'leri desktop'a gönder, senkronize sonucu al.
  Future<Map<String, dynamic>> syncPasswords(
      List<Map<String, dynamic>> localPasswords,
      List<String> deletedUuids,
  ) async {
    final resp = await _req({
      'type':          'sync',
      'passwords':     localPasswords,
      'deleted_uuids': deletedUuids,
    });
    if (resp['type'] == 'error') throw Exception(resp['message']);
    final rawPasswords = resp['passwords'] as List<dynamic>;
    final rawDeleted   = resp['deleted_uuids'] as List<dynamic>? ?? [];
    return {
      'passwords':     rawPasswords.map((e) => Map<String, dynamic>.from(e as Map)).toList(),
      'deleted_uuids': rawDeleted.map((e) => e as String).toList(),
    };
  }

  void _checkOk(Map<String, dynamic> resp) {
    if (resp['type'] == 'error') throw Exception(resp['message']);
  }

  // ── Bağlantı Kapatma ─────────────────────────────────────────────────

  void close() {
    if (_closed) return;
    _closed = true;
    try { _sendMsg(_socket, {'type': 'close'}); } catch (_) {}
    _reader.dispose();
    _socket.destroy();
  }

  // ── TCP yardımcıları ─────────────────────────────────────────────────

  static void _sendMsg(Socket socket, Map<String, dynamic> payload) {
    final body   = utf8.encode(jsonEncode(payload));
    final header = ByteData(4)..setUint32(0, body.length, Endian.big);
    socket.add(header.buffer.asUint8List());
    socket.add(body);
  }
}

// ── Byte okuyucu (auth_service ile aynı mantık) ───────────────────────────

class _ByteReader {
  final _buf = BytesBuilder(copy: false);
  Completer<void>? _waiter;
  bool _closed = false;
  late final StreamSubscription<Uint8List> _sub;

  _ByteReader(Socket socket) {
    _sub = socket.cast<Uint8List>().listen(
      (data) {
        _buf.add(data);
        final w = _waiter; _waiter = null; w?.complete();
      },
      onDone: () { _closed = true; _waiter?.completeError(Exception('Bağlantı kapandı')); _waiter = null; },
      onError: (Object e) { _closed = true; _waiter?.completeError(e); _waiter = null; },
    );
  }

  Future<Uint8List> _readExact(int n) async {
    while (_buf.length < n) {
      if (_closed) throw Exception('Bağlantı beklenmedik şekilde kapandı');
      _waiter = Completer<void>();
      await _waiter!.future;
    }
    final all    = _buf.toBytes();
    final result = Uint8List.fromList(all.sublist(0, n));
    _buf.clear();
    if (all.length > n) _buf.add(all.sublist(n));
    return result;
  }

  Future<Map<String, dynamic>> recvMsg() async {
    final lenBytes = await _readExact(4);
    final msgLen   = ByteData.sublistView(lenBytes).getUint32(0, Endian.big);
    if (msgLen > 65536) throw Exception('Mesaj çok büyük');
    final msgBytes = await _readExact(msgLen);
    return jsonDecode(utf8.decode(msgBytes)) as Map<String, dynamic>;
  }

  void dispose() => _sub.cancel();
}
