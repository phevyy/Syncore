import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'package:crypto/crypto.dart';

/// Auth sonucu.
class AuthResult {
  final bool success;
  final String? errorMessage;

  const AuthResult._({required this.success, this.errorMessage});

  factory AuthResult.ok()              => const AuthResult._(success: true);
  factory AuthResult.fail(String msg)  => AuthResult._(success: false, errorMessage: msg);
}

/// Desktop network_server.py ile aynı protokol:
///   → 4-byte big-endian length prefix + UTF-8 JSON body
///   Akış: auth_request → challenge → response → success/error
class AuthService {
  static const _port    = 8765;
  static const _timeout = Duration(seconds: 15);

  static Future<AuthResult> authenticate({
    required String serverIp,
    required String username,
    required String passwordSha256B64, // base64(SHA-256(password))
  }) async {
    Socket? socket;
    _ByteReader? reader;

    try {
      socket = await Socket.connect(serverIp, _port, timeout: _timeout);
      socket.setOption(SocketOption.tcpNoDelay, true);
      reader = _ByteReader(socket);

      // 1. auth_request — username + password_hash (TOFU için) ile birlikte gönder
      _sendMsg(socket, {
        'type': 'auth_request',
        'device_id': 1,
        'username': username,
        'password_hash': passwordSha256B64,
      });

      // 2. challenge al
      final challengeMsg = await reader.recvMsg().timeout(_timeout);
      if (challengeMsg['type'] != 'challenge') {
        return AuthResult.fail('Beklenmedik yanıt: ${challengeMsg['type']}');
      }

      // 3. HMAC-SHA256 — key = SHA-256(password)
      final sharedSecret = base64.decode(passwordSha256B64);
      final challenge    = base64.decode(challengeMsg['challenge'] as String);
      final digest       = Hmac(sha256, sharedSecret).convert(challenge);
      final responseB64  = base64.encode(digest.bytes);

      // 4. response gönder
      _sendMsg(socket, {
        'type': 'response',
        'response': responseB64,
        'device_id': 1,
      });

      // 5. sonuç al
      final result = await reader.recvMsg().timeout(_timeout);

      if (result['type'] == 'success') {
        return AuthResult.ok();
      } else {
        return AuthResult.fail(
          result['message'] as String? ?? 'Doğrulama başarısız',
        );
      }
    } on TimeoutException {
      return AuthResult.fail('Bağlantı zaman aşımı (15s)');
    } on SocketException catch (e) {
      return AuthResult.fail('Sunucuya erişilemiyor: ${e.message}');
    } on FormatException catch (e) {
      return AuthResult.fail('Protokol hatası: $e');
    } catch (e) {
      return AuthResult.fail(e.toString());
    } finally {
      reader?.dispose();
      socket?.destroy();
    }
  }

  static void _sendMsg(Socket socket, Map<String, dynamic> payload) {
    final body   = utf8.encode(jsonEncode(payload));
    final header = ByteData(4)..setUint32(0, body.length, Endian.big);
    socket.add(header.buffer.asUint8List());
    socket.add(body);
  }
}

/// Stream tabanlı Socket üzerinde tam byte okuma.
class _ByteReader {
  final _buf = BytesBuilder(copy: false);
  Completer<void>? _waiter;
  bool _closed = false;
  late final StreamSubscription<Uint8List> _sub;

  _ByteReader(Socket socket) {
    _sub = socket.cast<Uint8List>().listen(
      (data) {
        _buf.add(data);
        final w = _waiter;
        _waiter = null;
        w?.complete();
      },
      onDone: () {
        _closed = true;
        _waiter?.completeError(Exception('Bağlantı kapandı'));
        _waiter = null;
      },
      onError: (Object e) {
        _closed = true;
        _waiter?.completeError(e);
        _waiter = null;
      },
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
    if (msgLen > 65536) throw Exception('Mesaj çok büyük: $msgLen byte');
    final msgBytes = await _readExact(msgLen);
    return jsonDecode(utf8.decode(msgBytes)) as Map<String, dynamic>;
  }

  void dispose() => _sub.cancel();
}
