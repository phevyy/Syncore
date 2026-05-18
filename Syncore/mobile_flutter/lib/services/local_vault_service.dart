import 'dart:convert';
import 'dart:io';
import 'package:encrypt/encrypt.dart' as enc;
import 'package:path/path.dart' as p;
import 'package:sqflite/sqflite.dart';
import 'package:sqflite/sql.dart' show ConflictAlgorithm;
import 'package:uuid/uuid.dart';

/// Cihaz üzerinde yerel, şifreli şifre deposu.
/// Masaüstü bağlantısı olmadan tam CRUD desteği sağlar.
class LocalVaultService {
  static Database? _db;
  static enc.Key? _key;
  static const _uuid = Uuid();
  static const _dbName = 'local_vault.db';

  static bool get isInitialized => _db != null && _key != null;

  /// Vault'u başlat. passwordSha256B64 = base64(SHA-256(parola)) — 32 byte.
  static Future<void> init(String passwordSha256B64) async {
    _key = enc.Key(base64.decode(passwordSha256B64));
    final dbPath = p.join(await getDatabasesPath(), _dbName);
    _db = await openDatabase(
      dbPath,
      onCreate: (db, _) async {
        await db.execute('''
          CREATE TABLE passwords (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            uuid        TEXT    UNIQUE NOT NULL,
            title       TEXT    NOT NULL,
            username    TEXT    DEFAULT '',
            pwd_enc     TEXT    NOT NULL,
            url         TEXT    DEFAULT '',
            notes       TEXT    DEFAULT '',
            is_favorite INTEGER DEFAULT 0,
            is_trashed  INTEGER DEFAULT 0,
            created_at  TEXT    NOT NULL,
            modified_at TEXT    NOT NULL
          )
        ''');
        await db.execute('''
          CREATE TABLE deleted_uuids (
            uuid       TEXT PRIMARY KEY,
            deleted_at TEXT NOT NULL
          )
        ''');
      },
      onUpgrade: (db, oldVersion, newVersion) async {
        if (oldVersion < 2) {
          await db.execute('''
            CREATE TABLE IF NOT EXISTS deleted_uuids (
              uuid       TEXT PRIMARY KEY,
              deleted_at TEXT NOT NULL
            )
          ''');
        }
      },
      version: 2,
    );
  }

  /// Yerel veritabanını sil (çıkış yaparken).
  static Future<void> clearAll() async {
    _db?.close();
    _db  = null;
    _key = null;
    final dbPath = p.join(await getDatabasesPath(), _dbName);
    final f = File(dbPath);
    if (await f.exists()) await f.delete();
  }

  // ── Şifreleme ─────────────────────────────────────────────────────────

  static String _encrypt(String plaintext) {
    final iv        = enc.IV.fromSecureRandom(12);
    final encrypter = enc.Encrypter(enc.AES(_key!, mode: enc.AESMode.gcm));
    final encrypted = encrypter.encrypt(plaintext, iv: iv);
    return '${base64.encode(iv.bytes)}:${encrypted.base64}';
  }

  static String _decrypt(String ciphertext) {
    final idx       = ciphertext.indexOf(':');
    final iv        = enc.IV(base64.decode(ciphertext.substring(0, idx)));
    final encrypter = enc.Encrypter(enc.AES(_key!, mode: enc.AESMode.gcm));
    return encrypter.decrypt(
      enc.Encrypted.fromBase64(ciphertext.substring(idx + 1)),
      iv: iv,
    );
  }

  static String _now() => DateTime.now().toUtc().toIso8601String();

  // ── Yardımcı: satırı Map'e çevir (şifre hariç) ─────────────────────

  static Map<String, dynamic> _rowToMap(Map<String, dynamic> r) => {
    'id':          r['id'],
    'uuid':        r['uuid'],
    'title':       r['title'],
    'username':    r['username'] ?? '',
    'url':         r['url']     ?? '',
    'notes':       r['notes']   ?? '',
    'is_favorite': r['is_favorite'] == 1,
    'is_trashed':  r['is_trashed']  == 1,
    'created_at':  r['created_at'],
    'modified_at': r['modified_at'],
  };

  // ── CRUD ──────────────────────────────────────────────────────────────

  static Future<List<Map<String, dynamic>>> listPasswords({
    bool favoritesOnly = false,
    bool trashedOnly   = false,
  }) async {
    final db = _db!;
    String where = trashedOnly ? 'is_trashed = 1' : 'is_trashed = 0';
    if (favoritesOnly && !trashedOnly) where += ' AND is_favorite = 1';
    final rows = await db.query('passwords',
        where: where, orderBy: 'modified_at DESC');
    return rows.map(_rowToMap).toList();
  }

  static Future<String> getPassword(int id) async {
    final rows = await _db!.query('passwords',
        columns: ['pwd_enc'], where: 'id = ?', whereArgs: [id]);
    if (rows.isEmpty) throw Exception('Şifre bulunamadı (id=$id)');
    return _decrypt(rows.first['pwd_enc'] as String);
  }

  static Future<int> addPassword({
    required String title,
    required String username,
    required String password,
    String url   = '',
    String notes = '',
    String? uuid,
  }) async {
    final now = _now();
    return _db!.insert('passwords', {
      'uuid':        uuid ?? _uuid.v4(),
      'title':       title,
      'username':    username,
      'pwd_enc':     _encrypt(password),
      'url':         url,
      'notes':       notes,
      'is_favorite': 0,
      'is_trashed':  0,
      'created_at':  now,
      'modified_at': now,
    }, conflictAlgorithm: ConflictAlgorithm.ignore);
  }

  static Future<void> updatePassword(int id, {
    String? title,
    String? username,
    String? password,
    String? url,
    String? notes,
  }) async {
    final updates = <String, dynamic>{'modified_at': _now()};
    if (title    != null) updates['title']    = title;
    if (username != null) updates['username'] = username;
    if (password != null) updates['pwd_enc']  = _encrypt(password);
    if (url      != null) updates['url']      = url;
    if (notes    != null) updates['notes']    = notes;
    await _db!.update('passwords', updates,
        where: 'id = ?', whereArgs: [id]);
  }

  static Future<void> trashPassword(int id) async =>
      _db!.update('passwords', {'is_trashed': 1, 'modified_at': _now()},
          where: 'id = ?', whereArgs: [id]);

  static Future<void> restorePassword(int id) async =>
      _db!.update('passwords', {'is_trashed': 0, 'modified_at': _now()},
          where: 'id = ?', whereArgs: [id]);

  static Future<void> deletePassword(int id) async {
    final rows = await _db!.query('passwords',
        columns: ['uuid'], where: 'id = ?', whereArgs: [id]);
    if (rows.isNotEmpty) {
      final uuid = rows.first['uuid'] as String?;
      if (uuid != null && uuid.isNotEmpty) await _recordDeleted(uuid);
    }
    await _db!.delete('passwords', where: 'id = ?', whereArgs: [id]);
  }

  static Future<void> toggleFavorite(int id) async {
    final rows = await _db!.query('passwords',
        columns: ['is_favorite'], where: 'id = ?', whereArgs: [id]);
    if (rows.isEmpty) return;
    final cur = rows.first['is_favorite'] as int;
    await _db!.update('passwords',
        {'is_favorite': cur == 1 ? 0 : 1, 'modified_at': _now()},
        where: 'id = ?', whereArgs: [id]);
  }

  // ── UUID bazlı CRUD (online session sonrası local güncelleme) ─────────

  static Future<void> trashByUuid(String uuid) async =>
      _db!.update('passwords', {'is_trashed': 1, 'modified_at': _now()},
          where: 'uuid = ?', whereArgs: [uuid]);

  static Future<void> restoreByUuid(String uuid) async =>
      _db!.update('passwords', {'is_trashed': 0, 'modified_at': _now()},
          where: 'uuid = ?', whereArgs: [uuid]);

  static Future<void> deleteByUuid(String uuid,
      {bool recordTombstone = true}) async {
    if (recordTombstone) await _recordDeleted(uuid);
    await _db!.delete('passwords', where: 'uuid = ?', whereArgs: [uuid]);
  }

  // ── Tombstone yönetimi ────────────────────────────────────────────────

  static Future<void> _recordDeleted(String uuid) async =>
      _db!.insert('deleted_uuids', {'uuid': uuid, 'deleted_at': _now()},
          conflictAlgorithm: ConflictAlgorithm.ignore);

  static Future<List<String>> getPendingDeletedUuids() async {
    final rows = await _db!.query('deleted_uuids', columns: ['uuid']);
    return rows.map((r) => r['uuid'] as String).toList();
  }

  static Future<void> clearPendingDeletedUuids() async =>
      _db!.delete('deleted_uuids');

  static Future<void> toggleFavByUuid(String uuid) async {
    final rows = await _db!.query('passwords',
        columns: ['is_favorite'], where: 'uuid = ?', whereArgs: [uuid]);
    if (rows.isEmpty) return;
    final cur = rows.first['is_favorite'] as int;
    await _db!.update('passwords',
        {'is_favorite': cur == 1 ? 0 : 1, 'modified_at': _now()},
        where: 'uuid = ?', whereArgs: [uuid]);
  }

  static Future<void> updateByUuid(String uuid, {
    String? title,
    String? username,
    String? password,
    String? url,
    String? notes,
  }) async {
    final updates = <String, dynamic>{'modified_at': _now()};
    if (title    != null) updates['title']    = title;
    if (username != null) updates['username'] = username;
    if (password != null) updates['pwd_enc']  = _encrypt(password);
    if (url      != null) updates['url']      = url;
    if (notes    != null) updates['notes']    = notes;
    await _db!.update('passwords', updates,
        where: 'uuid = ?', whereArgs: [uuid]);
  }

  // ── Senkronizasyon ────────────────────────────────────────────────────

  /// Tüm şifreleri şifre metinleriyle birlikte dışa aktar.
  static Future<List<Map<String, dynamic>>> exportAllForSync() async {
    final rows = await _db!.query('passwords');
    return rows.map((r) {
      String pwd = '';
      try { pwd = _decrypt(r['pwd_enc'] as String); } catch (_) {}
      return {
        'uuid':        r['uuid'],
        'title':       r['title'],
        'username':    r['username'] ?? '',
        'password':    pwd,
        'url':         r['url']     ?? '',
        'notes':       r['notes']   ?? '',
        'is_favorite': r['is_favorite'] == 1,
        'is_trashed':  r['is_trashed']  == 1,
        'created_at':  r['created_at'],
        'modified_at': r['modified_at'],
      };
    }).toList();
  }

  /// Desktop'tan gelen şifreleri ve silinmiş UUID'leri yerel DB'ye uygula.
  static Future<void> importFromSync(
      List<Map<String, dynamic>> desktopPasswords, {
      List<String> desktopDeletedUuids = const [],
  }) async {
    // Desktop'ın sildiği kayıtları local'den de sil (tombstone kaydetme)
    for (final uuid in desktopDeletedUuids) {
      await deleteByUuid(uuid, recordTombstone: false);
    }
    // Kendi tombstone'larımızı temizle (desktop artık biliyor)
    await clearPendingDeletedUuids();
    final db = _db!;
    for (final dp in desktopPasswords) {
      final uuidVal = dp['uuid'] as String? ?? '';
      if (uuidVal.isEmpty) continue;

      final existing = await db.query('passwords',
          columns: ['id', 'modified_at'],
          where: 'uuid = ?', whereArgs: [uuidVal]);

      final isFav     = dp['is_favorite'] == true || dp['is_favorite'] == 1 ? 1 : 0;
      final isTrashed = dp['is_trashed']  == true || dp['is_trashed']  == 1 ? 1 : 0;
      final deskMod   = dp['modified_at'] as String? ?? _now();
      final now       = _now();

      if (existing.isEmpty) {
        String pwd = '';
        try { pwd = dp['password'] as String? ?? ''; } catch (_) {}
        await db.insert('passwords', {
          'uuid':        uuidVal,
          'title':       dp['title'],
          'username':    dp['username'] ?? '',
          'pwd_enc':     _encrypt(pwd),
          'url':         dp['url']     ?? '',
          'notes':       dp['notes']   ?? '',
          'is_favorite': isFav,
          'is_trashed':  isTrashed,
          'created_at':  dp['created_at'] ?? now,
          'modified_at': deskMod,
        });
      } else {
        final localMod = existing.first['modified_at'] as String? ?? '';
        if (deskMod.compareTo(localMod) > 0) {
          String pwd = '';
          try { pwd = dp['password'] as String? ?? ''; } catch (_) {}
          await db.update('passwords', {
            'title':       dp['title'],
            'username':    dp['username'] ?? '',
            'pwd_enc':     _encrypt(pwd),
            'url':         dp['url']     ?? '',
            'notes':       dp['notes']   ?? '',
            'is_favorite': isFav,
            'is_trashed':  isTrashed,
            'modified_at': deskMod,
          }, where: 'uuid = ?', whereArgs: [uuidVal]);
        }
      }
    }
  }
}
