import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:uuid/uuid.dart';
import '../app_theme.dart';
import '../services/local_vault_service.dart';
import '../services/storage_service.dart';
import '../services/vault_service.dart';

const _uuid = Uuid();

/// Şifre yöneticisi.
/// Offline: LocalVaultService (yerel SQLite)
/// Online: VaultSession (desktop TCP) — QR scan ile bağlanıldığında aktif.
/// QR bağlantısında iki taraf senkronize edilir (UUID bazlı, last-modified-wins).
class VaultScreen extends StatefulWidget {
  const VaultScreen({super.key});

  @override
  State<VaultScreen> createState() => _VaultScreenState();
}

class _VaultScreenState extends State<VaultScreen> {
  VaultSession? _session;
  List<Map<String, dynamic>> _entries = [];
  bool _loading  = true;
  bool _offline  = false;
  bool _syncing  = false;
  String? _error;
  String _filter          = 'all';
  String _activeCategory  = '';
  String _searchQ = '';
  String _username = '';
  List<Map<String, dynamic>> _rawEntries = [];
  final _searchCtrl = TextEditingController();
  Timer? _pollTimer;
  Timer? _syncTimer;
  bool _isPollRunning = false;

  @override
  void initState() {
    super.initState();
    _init();
  }

  @override
  void dispose() {
    _pollTimer?.cancel(); _syncTimer?.cancel();
    _session?.close();
    _searchCtrl.dispose();
    super.dispose();
  }

  // ── Başlatma & Bağlantı ──────────────────────────────────────────────

  Future<void> _init() async {
    final creds = await StorageService.load();
    if (creds == null) {
      if (mounted) Navigator.pushNamedAndRemoveUntil(context, '/', (_) => false);
      return;
    }
    _username = creds.username;

    // Yerel vault'u başlat (hata olursa devam et)
    try {
      await LocalVaultService.init(creds.passwordSha256B64);
      await _loadFromLocal();
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }

    // Her zaman offline başla — bağlantı sadece QR tarama ile olur
    if (mounted) setState(() => _offline = true);
  }

  Future<void> _connectToDesktop(
      ({String username, String passwordSha256B64, String? serverIp}) creds) async {
    _pollTimer?.cancel(); _syncTimer?.cancel();
    _session?.close();
    _session = null;

    // Desktop manager server'ının açılması için kısa retry (TFA → CRUD geçiş süresi)
    Exception? lastErr;
    for (int attempt = 0; attempt < 3; attempt++) {
      if (attempt > 0) await Future.delayed(const Duration(milliseconds: 800));
      try {
        _session = await VaultSession.connect(
          serverIp:          creds.serverIp!,
          username:          creds.username,
          passwordSha256B64: creds.passwordSha256B64,
        );
        lastErr = null;
        break;
      } catch (e) {
        lastErr = e is Exception ? e : Exception(e.toString());
      }
    }
    if (lastErr != null) {
      _session = null;
      if (mounted) setState(() { _offline = true; _syncing = false; });
      return;
    }

    // Bağlantı kuruldu — banner'ı hemen kaldır, sync spinner göster
    if (mounted) setState(() { _offline = false; _syncing = true; });
    try {
      await _syncWithDesktop();
      if (mounted) setState(() => _syncing = false);
      await _loadFromSession();
      _startPolling();
    } catch (_) {
      _session = null;
      if (mounted) setState(() { _offline = true; _syncing = false; });
    }
  }

  /// QR scan AppBar butonuna basıldığında
  Future<void> _scanQr() async {
    _pollTimer?.cancel(); _syncTimer?.cancel();
    _session?.close();
    _session = null;
    // Eski IP'yi temizle — sadece yeni QR taranırsa bağlanılır
    await StorageService.clearServerIp();
    await Navigator.pushNamed(context, '/scan');
    if (!mounted) return;
    final creds = await StorageService.load();
    if (creds == null || creds.serverIp == null) return;
    await _connectToDesktop(creds);
  }

  Future<void> _onLogout() async {
    _pollTimer?.cancel(); _syncTimer?.cancel();
    _session?.close();
    await LocalVaultService.clearAll();
    await StorageService.clear();
    if (!mounted) return;
    Navigator.pushNamedAndRemoveUntil(context, '/', (_) => false);
  }

  void _startPolling() {
    _pollTimer?.cancel(); _syncTimer?.cancel();
    _syncTimer?.cancel();

    // Hafif poll: sadece değişiklik var mı kontrol et, ekranı güncelle
    _pollTimer = Timer.periodic(const Duration(seconds: 1), (_) async {
      if (_session == null || !mounted || _isPollRunning) return;
      _isPollRunning = true;
      try {
        final changed = await _session!.pollEvents();
        if (changed && mounted) await _loadFromSession();
      } catch (_) {
        _session?.close();
        _session = null;
        _pollTimer?.cancel(); _syncTimer?.cancel();
        _syncTimer?.cancel();
        if (mounted) {
          setState(() => _offline = true);
          await _loadFromLocal();
        }
      } finally {
        _isPollRunning = false;
      }
    });

    // Ağır sync: yerel vault'u 15 saniyede bir desktop ile eşleştir
    _syncTimer = Timer.periodic(const Duration(seconds: 15), (_) async {
      if (_session == null || !mounted || _isPollRunning) return;
      _isPollRunning = true;
      try { await _syncWithDesktop(); } catch (_) {}
      finally { _isPollRunning = false; }
    });
  }

  /// Online op başarısız olursa session'ı kapat, offline op'a geç.
  /// [onOnlineSuccess]: online başarılıysa local'e de aynı işlemi uygula.
  Future<T> _withFallback<T>(
    Future<T> Function() online,
    Future<T> Function() offline, {
    Future<void> Function()? onOnlineSuccess,
  }) async {
    if (_session != null) {
      try {
        final result = await online();
        if (onOnlineSuccess != null) {
          try { await onOnlineSuccess(); } catch (_) {}
        }
        return result;
      } catch (_) {
        _session?.close();
        _session = null;
        _pollTimer?.cancel(); _syncTimer?.cancel();
        if (mounted) setState(() => _offline = true);
      }
    }
    return await offline();
  }

  /// _entries'ten UUID'yi UUID'yi bul (online modda desktop UUID'si döner).
  String? _entryUuid(int id) {
    try {
      return _entries.firstWhere((e) => (e['id'] as num).toInt() == id)['uuid']
          as String?;
    } catch (_) { return null; }
  }

  // ── Senkronizasyon ────────────────────────────────────────────────────

  Future<void> _syncWithDesktop() async {
    if (_session == null || !LocalVaultService.isInitialized) return;
    try {
      final local        = await LocalVaultService.exportAllForSync();
      final deletedUuids = await LocalVaultService.getPendingDeletedUuids();
      final result       = await _session!.syncPasswords(local, deletedUuids);
      final desktopPasswords = (result['passwords'] as List)
          .map((e) => Map<String, dynamic>.from(e as Map)).toList();
      final desktopDeleted = (result['deleted_uuids'] as List<dynamic>? ?? [])
          .map((e) => e as String).toList();
      await LocalVaultService.importFromSync(
        desktopPasswords,
        desktopDeletedUuids: desktopDeleted,
      );
    } catch (_) {}
  }

  // ── Yükleme ───────────────────────────────────────────────────────────

  Future<void> _load() async {
    if (_session != null) {
      await _loadFromSession();
    } else {
      await _loadFromLocal();
    }
  }

  Future<void> _loadFromSession() async {
    if (_session == null) return;
    try { await _doLoadFromSession(); } catch (_) {
      _session?.close();
      _session = null;
      _pollTimer?.cancel(); _syncTimer?.cancel();
      if (mounted) setState(() => _offline = true);
      await _loadFromLocal();
    }
  }

  Future<void> _doLoadFromSession() async {
    if (_session == null) return;
    try {
      final entries = await _session!.listPasswords(
        favoritesOnly: _filter == 'favorites',
        trashedOnly:   _filter == 'trash',
      );
      if (!mounted) return;

      List<Map<String, dynamic>> result = entries;

      if (_filter == 'weak') {
        final weak = <Map<String, dynamic>>[];
        for (final e in entries) {
          try {
            final pwd = await _session!.getPassword((e['id'] as num).toInt());
            if (_strengthKey(pwd) == 'weak') weak.add({...e, '_pwd': pwd});
          } catch (_) {}
        }
        result = weak;
      }

      if (_searchQ.isNotEmpty) {
        final q = _searchQ.toLowerCase();
        result = result.where((e) =>
            (e['title'] as String? ?? '').toLowerCase().contains(q)).toList();
      }

      final raw = result.toList();
      if (_activeCategory.isNotEmpty) {
        result = result.where((e) {
          final cat = _getCategory(e['title'] as String? ?? '');
          return cat != null && cat.$1 == _activeCategory;
        }).toList();
      }

      if (mounted) setState(() { _entries = result; _rawEntries = raw; _loading = false; _error = null; });
    } catch (e) {
      rethrow;
    }
  }

  Future<void> _loadFromLocal() async {
    if (!LocalVaultService.isInitialized) {
      if (mounted) setState(() => _loading = false);
      return;
    }
    try {
      List<Map<String, dynamic>> result;

      if (_filter == 'weak') {
        final all = await LocalVaultService.listPasswords();
        final weak = <Map<String, dynamic>>[];
        for (final e in all) {
          try {
            final pwd = await LocalVaultService.getPassword((e['id'] as num).toInt());
            if (_strengthKey(pwd) == 'weak') weak.add({...e, '_pwd': pwd});
          } catch (_) {}
        }
        result = weak;
      } else {
        result = await LocalVaultService.listPasswords(
          favoritesOnly: _filter == 'favorites',
          trashedOnly:   _filter == 'trash',
        );
      }

      if (_searchQ.isNotEmpty) {
        final q = _searchQ.toLowerCase();
        result = result.where((e) =>
            (e['title'] as String? ?? '').toLowerCase().contains(q)).toList();
      }

      final raw = result.toList();
      if (_activeCategory.isNotEmpty) {
        result = result.where((e) {
          final cat = _getCategory(e['title'] as String? ?? '');
          return cat != null && cat.$1 == _activeCategory;
        }).toList();
      }

      if (mounted) setState(() { _entries = result; _rawEntries = raw; _loading = false; _error = null; });
    } catch (e) {
      if (mounted) setState(() { _error = e.toString(); _loading = false; });
    }
  }

  // ── UI ────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(_username.isEmpty ? 'Şifrelerim' : '$_username\'in Kasası'),
        actions: [
          if (_syncing)
            const Padding(
              padding: EdgeInsets.symmetric(horizontal: 12, vertical: 14),
              child: SizedBox(
                width: 18, height: 18,
                child: CircularProgressIndicator(
                    color: AppColors.accent, strokeWidth: 2),
              ),
            )
          else if (_offline && _session == null)
            Container(
              margin: const EdgeInsets.symmetric(vertical: 8, horizontal: 4),
              padding: const EdgeInsets.symmetric(horizontal: 8),
              decoration: BoxDecoration(
                color: AppColors.warn.withValues(alpha: 0.15),
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: AppColors.warn.withValues(alpha: 0.4)),
              ),
              child: const Center(
                child: Text('Çevrimdışı',
                    style: TextStyle(color: AppColors.warn, fontSize: 11)),
              ),
            ),
          IconButton(
            icon: const Icon(Icons.qr_code_scanner),
            onPressed: _scanQr,
            tooltip: 'Desktop\'a Bağlan (QR)',
          ),
          if (_session != null)
            IconButton(
              icon: const Icon(Icons.refresh),
              onPressed: _load,
              tooltip: 'Yenile',
            ),
          TextButton.icon(
            onPressed: _onLogout,
            icon: const Icon(Icons.logout, size: 18, color: Color(0xFFEF4444)),
            label: const Text('Çıkış',
                style: TextStyle(color: Color(0xFFEF4444), fontSize: 13)),
          ),
        ],
      ),
      body: Column(children: [
        if (_offline && _session == null && !_syncing) _buildOfflineBanner(),
        _buildSearch(),
        _buildFilterChips(),
        Expanded(child: _buildBody()),
      ]),
      floatingActionButton: _filter == 'trash'
          ? null
          : FloatingActionButton(
              onPressed: _showAddDialog,
              backgroundColor: AppColors.accent,
              child: const Icon(Icons.add, color: Colors.white),
            ),
    );
  }

  Widget _buildOfflineBanner() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      color: AppColors.warn.withValues(alpha: 0.08),
      child: Row(children: [
        const Icon(Icons.wifi_off, color: AppColors.warn, size: 15),
        const SizedBox(width: 8),
        const Expanded(
          child: Text('Masaüstüne bağlı değil — yerel depo',
              style: TextStyle(color: AppColors.warn, fontSize: 12)),
        ),
        TextButton(
          onPressed: () async {
            final creds = await StorageService.load();
            if (creds?.serverIp != null && mounted) _connectToDesktop(creds!);
          },
          style: TextButton.styleFrom(
              padding: EdgeInsets.zero,
              minimumSize: const Size(0, 0),
              tapTargetSize: MaterialTapTargetSize.shrinkWrap),
          child: const Text('Dene',
              style: TextStyle(color: AppColors.accent, fontSize: 12)),
        ),
      ]),
    );
  }

  Widget _buildSearch() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
      child: TextField(
        controller: _searchCtrl,
        style: const TextStyle(color: AppColors.text),
        decoration: InputDecoration(
          hintText: 'Şifre ara...',
          prefixIcon: const Icon(Icons.search, color: AppColors.textSub, size: 20),
          suffixIcon: _searchQ.isNotEmpty
              ? IconButton(
                  icon: const Icon(Icons.clear, color: AppColors.textSub, size: 18),
                  onPressed: () {
                    _searchCtrl.clear();
                    setState(() => _searchQ = '');
                    _load();
                  })
              : null,
          contentPadding: const EdgeInsets.symmetric(vertical: 10),
        ),
        onChanged: (v) { setState(() => _searchQ = v); _load(); },
      ),
    );
  }

  Widget _buildFilterChips() {
    final filters = [
      ('all',       'Tümü',      Icons.list),
      ('favorites', '⭐ Favori', Icons.star),
      ('weak',      '⚠ Zayıf',  Icons.warning),
      ('trash',     '🗑 Çöp',    Icons.delete),
    ];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          height: 44,
          child: ListView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
            children: filters.map((f) {
              final active = _filter == f.$1;
              return Padding(
                padding: const EdgeInsets.only(right: 8),
                child: ChoiceChip(
                  label: Text(f.$2),
                  selected: active,
                  onSelected: (_) {
                    setState(() {
                      _filter = f.$1;
                      _activeCategory = '';
                      _searchQ = '';
                      _searchCtrl.clear();
                    });
                    _load();
                  },
                  selectedColor: AppColors.accent,
                  backgroundColor: AppColors.surface,
                  labelStyle: TextStyle(
                      color: active ? Colors.white : AppColors.textSub,
                      fontSize: 13),
                ),
              );
            }).toList(),
          ),
        ),
        _buildCategoryChips(),
      ],
    );
  }

  Widget _buildCategoryChips() {
    final counts = <String, (String, int)>{};
    for (final e in _rawEntries) {
      final cat = _getCategory(e['title'] as String? ?? '');
      if (cat != null) {
        final prev = counts[cat.$1];
        counts[cat.$1] = (cat.$2, (prev?.$2 ?? 0) + 1);
      }
    }
    if (counts.isEmpty) return const SizedBox.shrink();

    final sorted = counts.entries.toList()
      ..sort((a, b) => b.value.$2.compareTo(a.value.$2));

    return SizedBox(
      height: 40,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.fromLTRB(12, 0, 12, 6),
        children: sorted.map((entry) {
          final active = _activeCategory == entry.key;
          return Padding(
            padding: const EdgeInsets.only(right: 8),
            child: ChoiceChip(
              label: Text('${entry.value.$1} ${entry.key}  ${entry.value.$2}'),
              selected: active,
              onSelected: (_) {
                setState(() {
                  _activeCategory = active ? '' : entry.key;
                });
                _load();
              },
              selectedColor: AppColors.accent,
              backgroundColor: AppColors.surface,
              labelStyle: TextStyle(
                  color: active ? Colors.white : AppColors.textSub,
                  fontSize: 11),
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 0),
            ),
          );
        }).toList(),
      ),
    );
  }

  Widget _buildBody() {
    if (_loading) {
      return const Center(
          child: CircularProgressIndicator(color: AppColors.accent));
    }
    if (_error != null && _entries.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            const Icon(Icons.error_outline, color: AppColors.danger, size: 48),
            const SizedBox(height: 12),
            Text(_error!,
                style: const TextStyle(color: AppColors.danger),
                textAlign: TextAlign.center),
            const SizedBox(height: 20),
            ElevatedButton(onPressed: _load, child: const Text('Yeniden Dene')),
          ]),
        ),
      );
    }
    if (_entries.isEmpty) {
      return Center(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Text(
            _searchQ.isNotEmpty
                ? 'Sonuç bulunamadı.'
                : _filter == 'trash'
                    ? 'Çöp kutusu boş.'
                    : 'Henüz şifre yok.',
            style: const TextStyle(color: AppColors.textSub),
          ),
          if (_filter == 'all' && _searchQ.isEmpty) ...[
            const SizedBox(height: 16),
            ElevatedButton.icon(
              onPressed: _showAddDialog,
              icon: const Icon(Icons.add),
              label: const Text('İlk Şifreyi Ekle'),
            ),
          ],
        ]),
      );
    }
    return RefreshIndicator(
      color: AppColors.accent,
      onRefresh: _load,
      child: ListView.builder(
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 80),
        itemCount: _entries.length,
        itemBuilder: (_, i) => _PasswordCard(
          entry:     _entries[i],
          inTrash:   _filter == 'trash',
          onCopy:    () => _copyPassword(_entries[i]),
          onView:    () => _showDetailDialog(_entries[i]),
          onEdit:    () => _showEditDialog(_entries[i]),
          onTrash:   () => _trash((_entries[i]['id'] as num).toInt()),
          onDelete:  () => _delete((_entries[i]['id'] as num).toInt()),
          onRestore: () => _restore((_entries[i]['id'] as num).toInt()),
          onFav:     () => _toggleFav((_entries[i]['id'] as num).toInt()),
        ),
      ),
    );
  }

  // ── CRUD — online: VaultSession, offline: LocalVaultService ──────────

  Future<void> _copyPassword(Map<String, dynamic> entry) async {
    final id = (entry['id'] as num).toInt();
    try {
      final pwd = await _withFallback(
        () => _session!.getPassword(id),
        () => LocalVaultService.getPassword(id),
      );
      await Clipboard.setData(ClipboardData(text: pwd));
      if (mounted) _snack('Şifre kopyalandı!');
    } catch (e) {
      if (mounted) _snack('Hata: $e', error: true);
    }
  }

  Future<void> _trash(int id) async {
    final uuid = _entryUuid(id);
    try {
      await _withFallback(
        () => _session!.trashPassword(id),
        () => LocalVaultService.trashPassword(id),
        onOnlineSuccess: uuid != null
            ? () => LocalVaultService.trashByUuid(uuid)
            : null,
      );
      await _load();
    } catch (e) { if (mounted) _snack('Hata: $e', error: true); }
  }

  Future<void> _delete(int id) async {
    final ok = await _confirm('Bu şifreyi kalıcı olarak sil?');
    if (!ok) return;
    final uuid = _entryUuid(id);
    try {
      await _withFallback(
        () => _session!.deletePassword(id),
        () => LocalVaultService.deletePassword(id),
        onOnlineSuccess: uuid != null
            ? () => LocalVaultService.deleteByUuid(uuid)
            : null,
      );
      await _load();
    } catch (e) { if (mounted) _snack('Hata: $e', error: true); }
  }

  Future<void> _restore(int id) async {
    final uuid = _entryUuid(id);
    try {
      await _withFallback(
        () => _session!.restorePassword(id),
        () => LocalVaultService.restorePassword(id),
        onOnlineSuccess: uuid != null
            ? () => LocalVaultService.restoreByUuid(uuid)
            : null,
      );
      await _load();
    } catch (e) { if (mounted) _snack('Hata: $e', error: true); }
  }

  Future<void> _toggleFav(int id) async {
    final uuid = _entryUuid(id);
    try {
      await _withFallback(
        () => _session!.toggleFavorite(id),
        () => LocalVaultService.toggleFavorite(id),
        onOnlineSuccess: uuid != null
            ? () => LocalVaultService.toggleFavByUuid(uuid)
            : null,
      );
      await _load();
    } catch (e) { if (mounted) _snack('Hata: $e', error: true); }
  }

  // ── Dialoglar ────────────────────────────────────────────────────────

  void _showDetailDialog(Map<String, dynamic> entry) {
    showDialog(
      context: context,
      builder: (_) => _DetailDialog(
        entry: entry,
        passwordFetcher: (i) => _withFallback(
          () => _session!.getPassword(i),
          () => LocalVaultService.getPassword(i),
        ),
      ),
    );
  }

  void _showAddDialog() {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: AppColors.surface,
      shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (_) => _PasswordForm(
        onSave: (data) async {
          final newUuid = _uuid.v4();
          await _withFallback(
            () => _session!.addPassword(
              title: data['title']!, username: data['username']!,
              password: data['password']!, url: data['url']!,
              notes: data['notes']!, uuid: newUuid,
            ),
            () => LocalVaultService.addPassword(
              title: data['title']!, username: data['username']!,
              password: data['password']!, url: data['url']!,
              notes: data['notes']!, uuid: newUuid,
            ),
            onOnlineSuccess: () => LocalVaultService.addPassword(
              title: data['title']!, username: data['username']!,
              password: data['password']!, url: data['url']!,
              notes: data['notes']!, uuid: newUuid,
            ),
          );
          await _load();
        },
      ),
    );
  }

  void _showEditDialog(Map<String, dynamic> entry) async {
    final id = (entry['id'] as num).toInt();
    String pwd = '';
    try {
      pwd = await _withFallback(
        () => _session!.getPassword(id),
        () => LocalVaultService.getPassword(id),
      );
    } catch (_) {}
    if (!mounted) return;
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: AppColors.surface,
      shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (_) => _PasswordForm(
        initial: {...entry, 'password': pwd},
        onSave: (data) async {
          final uuid = _entryUuid(id);
          await _withFallback(
            () => _session!.updatePassword(id,
              title: data['title'], username: data['username'],
              password: data['password'], url: data['url'], notes: data['notes'],
            ),
            () => LocalVaultService.updatePassword(id,
              title: data['title'], username: data['username'],
              password: data['password'], url: data['url'], notes: data['notes'],
            ),
            onOnlineSuccess: uuid != null
                ? () => LocalVaultService.updateByUuid(uuid,
                    title: data['title'], username: data['username'],
                    password: data['password'], url: data['url'],
                    notes: data['notes'])
                : null,
          );
          await _load();
        },
      ),
    );
  }

  // ── Yardımcılar ───────────────────────────────────────────────────────

  void _snack(String msg, {bool error = false}) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
      content: Text(msg),
      backgroundColor: error ? AppColors.danger : AppColors.success,
      duration: const Duration(seconds: 2),
    ));
  }

  Future<bool> _confirm(String msg) async {
    return await showDialog<bool>(
          context: context,
          builder: (_) => AlertDialog(
            backgroundColor: AppColors.surface,
            title: const Text('Onay', style: TextStyle(color: AppColors.text)),
            content: Text(msg, style: const TextStyle(color: AppColors.textSub)),
            actions: [
              TextButton(
                  onPressed: () => Navigator.pop(context, false),
                  child: const Text('İptal')),
              TextButton(
                  onPressed: () => Navigator.pop(context, true),
                  child: const Text('Evet',
                      style: TextStyle(color: AppColors.danger))),
            ],
          ),
        ) ??
        false;
  }
}

// ── Şifre Gücü ───────────────────────────────────────────────────────────────

String _strengthKey(String pwd) {
  if (pwd.isEmpty) return 'weak';
  int score = 0;
  if (pwd.length >= 8)  score += 20;
  if (pwd.length >= 12) score += 15;
  if (pwd.length >= 16) score += 15;
  if (RegExp(r'[A-Z]').hasMatch(pwd)) score += 15;
  if (RegExp(r'[a-z]').hasMatch(pwd)) score += 10;
  if (RegExp(r'\d').hasMatch(pwd))    score += 10;
  if (RegExp(r'[^A-Za-z0-9]').hasMatch(pwd)) score += 15;
  if (score < 40) return 'weak';
  if (score < 70) return 'medium';
  return 'strong';
}

String _siteEmoji(String title) {
  final t = title.toLowerCase();
  const map = {
    // E-posta
    'gmail': '📧', 'mail': '📧', 'email': '📧', 'e-posta': '📧',
    'eposta': '📧', 'outlook': '📧', 'hotmail': '📧', 'yahoo': '📧',
    'yandex': '📧', 'proton': '📧',
    // Bankacılık
    'banka': '🏦', 'bank': '🏦', 'finans': '🏦', 'finance': '🏦',
    'kredi': '🏦', 'credit': '🏦', 'dolar': '🏦', 'dollar': '🏦',
    'euro': '🏦', 'borsa': '🏦', 'invest': '🏦', 'wallet': '🏦',
    'cüzdan': '🏦', 'iban': '🏦', 'akbank': '🏦', 'garanti': '🏦',
    'yapıkredi': '🏦', 'ziraat': '🏦', 'halkbank': '🏦', 'vakıf': '🏦',
    // Kripto
    'bitcoin': '🪙', 'btc': '🪙', 'ethereum': '🪙', 'eth': '🪙',
    'binance': '🪙', 'kripto': '🪙', 'crypto': '🪙', 'coinbase': '🪙',
    'bybit': '🪙', 'metamask': '🪙',
    // Oyun
    'oyun': '🎮', 'game': '🎮', 'steam': '🎮', 'epic': '🎮',
    'xbox': '🎮', 'playstation': '🎮', 'nintendo': '🎮',
    'ubisoft': '🎮', 'riot': '🎮', 'minecraft': '🎮', 'roblox': '🎮',
    // Sosyal
    'instagram': '📸', 'tiktok': '📸', 'snapchat': '📸', 'pinterest': '📸',
    'twitter': '🐦',
    'facebook': '📘', 'messenger': '📘',
    'linkedin': '💼',
    'reddit': '🤖',
    // Mesajlaşma
    'whatsapp': '💬', 'telegram': '💬', 'signal': '💬', 'discord': '💬',
    'slack': '💬', 'viber': '💬', 'mesaj': '💬',
    // Video / Yayın
    'netflix': '🎬', 'youtube': '🎬', 'hulu': '🎬', 'disney': '🎬',
    'mubi': '🎬', 'blutv': '🎬', 'exxen': '🎬', 'twitch': '🎬',
    'vimeo': '🎬',
    // Müzik
    'spotify': '🎵', 'soundcloud': '🎵', 'deezer': '🎵', 'tidal': '🎵',
    'müzik': '🎵', 'music': '🎵',
    // Alışveriş
    'amazon': '🛒', 'trendyol': '🛒', 'hepsiburada': '🛒', 'etsy': '🛒',
    'ebay': '🛒', 'aliexpress': '🛒',
    // Bulut / Depolama
    'dropbox': '☁️', 'icloud': '☁️', 'onedrive': '☁️',
    'mega': '☁️', 'bulut': '☁️', 'cloud': '☁️', 'drive': '☁️',
    // Geliştirici
    'github': '💻', 'gitlab': '💻', 'bitbucket': '💻', 'docker': '💻',
    'heroku': '💻', 'vercel': '💻', 'netlify': '💻', 'aws': '💻',
    // Google
    'google': '🌐',
    // Apple
    'apple': '🍎', 'itunes': '🍎', 'appstore': '🍎',
    // Microsoft
    'microsoft': '🪟', 'windows': '🪟', 'office': '🪟',
    // Güvenlik
    'vpn': '🔒', 'ssh': '🔒', '2fa': '🔒', 'güvenlik': '🔒',
    'security': '🔒', 'firewall': '🔒',
    // Sunucu
    'server': '🖥️', 'sunucu': '🖥️', 'hosting': '🖥️',
    'linux': '🖥️', 'ftp': '🖥️', 'rdp': '🖥️',
    // Eğitim
    'okul': '🎓', 'university': '🎓', 'üniversite': '🎓', 'udemy': '🎓',
    'coursera': '🎓', 'duolingo': '🎓', 'eğitim': '🎓',
    // Sağlık
    'sağlık': '🏥', 'health': '🏥', 'hospital': '🏥', 'hastane': '🏥',
    'sigorta': '🏥',
    // Seyahat
    'seyahat': '✈️', 'travel': '✈️', 'airline': '✈️', 'hotel': '✈️',
    'otel': '✈️', 'airbnb': '✈️', 'booking': '✈️', 'thy': '✈️',
    'pegasus': '✈️',
    // Yemek
    'yemek': '🍔', 'food': '🍔', 'yemeksepeti': '🍔', 'getir': '🍔',
    'pizza': '🍔', 'burger': '🍔',
    // E-devlet
    'e-devlet': '🏛️', 'devlet': '🏛️', 'government': '🏛️',
    'sgk': '🏛️', 'belediye': '🏛️', 'vergi': '🏛️',
    // Ödeme
    'paypal': '💳', 'stripe': '💳', 'papara': '💳', 'ininal': '💳',
    'kart': '💳', 'visa': '💳', 'mastercard': '💳',
    // Video konferans
    'zoom': '📹', 'webex': '📹',
    // Telefon
    'telefon': '📱', 'turkcell': '📱', 'vodafone': '📱',
    // Not / Üretkenlik
    'notion': '📝', 'trello': '📝', 'jira': '📝', 'note': '📝',
  };
  for (final e in map.entries) {
    if (t.contains(e.key)) return e.value;
  }
  return '🔑';
}

/// Başlığa göre (categoryName, emoji) döner. Eşleşme yoksa null.
(String, String)? _getCategory(String title) {
  final t = title.toLowerCase();
  const cats = [
    (['getir', 'yemeksepeti', 'uber eat', 'ubereats', 'dominos', 'pizza',
       'burger', 'yemek', 'food', 'migros', 'market', 'a101', 'bim',
       'carrefour'], 'Yemek & Market', '🍔'),
    (['akbank', 'garanti', 'yapıkredi', 'ziraat', 'halkbank', 'isbank',
       'iş bank', 'vakıf', 'banka', 'bank', 'finans', 'finance', 'iban',
       'swift', 'borsa', 'invest', 'kredi', 'credit', 'papara',
       'ininal'], 'Banka & Finans', '🏦'),
    (['bitcoin', 'btc', 'ethereum', 'eth', 'binance', 'kripto', 'crypto',
       'coinbase', 'bybit', 'okx', 'kucoin', 'metamask'], 'Kripto', '🪙'),
    (['steam', 'epic', 'xbox', 'playstation', 'ps4', 'ps5', 'nintendo',
       'riot', 'league', 'minecraft', 'roblox', 'oyun', 'game', 'gog',
       'ubisoft', 'origin'], 'Oyun', '🎮'),
    (['whatsapp', 'telegram', 'signal', 'discord', 'slack', 'viber',
       'messenger', 'mesaj', 'skype'], 'Mesajlaşma', '💬'),
    (['instagram', 'tiktok', 'twitter', 'facebook', 'reddit', 'snapchat',
       'linkedin', 'pinterest', 'tumblr'], 'Sosyal Medya', '📱'),
    (['netflix', 'youtube', 'hulu', 'disney', 'mubi', 'blutv', 'exxen',
       'twitch', 'vimeo', 'gain', 'tod'], 'Eğlence', '🎬'),
    (['spotify', 'soundcloud', 'deezer', 'tidal', 'müzik', 'music',
       'apple music'], 'Müzik', '🎵'),
    (['gmail', 'mail', 'email', 'e-posta', 'eposta', 'outlook', 'hotmail',
       'yahoo', 'yandex', 'proton', 'imap'], 'E-posta', '📧'),
    (['amazon', 'trendyol', 'hepsiburada', 'n11', 'etsy', 'ebay',
       'aliexpress', 'shopify'], 'Alışveriş', '🛒'),
    (['github', 'gitlab', 'bitbucket', 'docker', 'heroku', 'vercel',
       'netlify', 'aws', 'azure', 'gcp', 'linux', 'hosting', 'server',
       'sunucu', 'ftp', 'rdp', 'ssh'], 'Geliştirici', '💻'),
    (['vpn', '2fa', 'güvenlik', 'security', 'firewall',
       'nordvpn', 'expressvpn'], 'Güvenlik', '🔒'),
    (['booking', 'airbnb', 'thy', 'pegasus', 'hotel', 'otel', 'seyahat',
       'travel', 'airline'], 'Seyahat', '✈️'),
    (['e-devlet', 'devlet', 'sgk', 'belediye', 'vergi',
       'government', 'meb'], 'Resmi', '🏛️'),
    (['google', 'apple', 'microsoft', 'icloud', 'drive', 'dropbox',
       'onedrive', 'mega', 'cloud', 'bulut', 'windows',
       'office'], 'Bulut & Hesap', '☁️'),
    (['okul', 'üniversite', 'university', 'udemy', 'coursera',
       'duolingo', 'eğitim'], 'Eğitim', '🎓'),
    (['sağlık', 'health', 'hospital', 'hastane', 'sigorta',
       'doktor'], 'Sağlık', '🏥'),
    (['turkcell', 'vodafone', 'türk telekom', 'telefon',
       'gsm', 'operatör'], 'Telekom', '📡'),
  ];
  for (final c in cats) {
    final kws = c.$1 as List<String>;
    if (kws.any((kw) => t.contains(kw))) return (c.$2 as String, c.$3 as String);
  }
  return null;
}

// ── Şifre Kartı ──────────────────────────────────────────────────────────────

class _PasswordCard extends StatelessWidget {
  final Map<String, dynamic> entry;
  final bool inTrash;
  final VoidCallback onCopy, onView, onEdit, onTrash, onDelete, onRestore, onFav;

  const _PasswordCard({
    required this.entry,
    required this.inTrash,
    required this.onCopy,
    required this.onView,
    required this.onEdit,
    required this.onTrash,
    required this.onDelete,
    required this.onRestore,
    required this.onFav,
  });

  @override
  Widget build(BuildContext context) {
    final title    = entry['title']    as String? ?? '';
    final username = entry['username'] as String? ?? '';
    final isFav    = entry['is_favorite'] == true || entry['is_favorite'] == 1;

    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      color: const Color(0xFF251E2B),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: BorderSide(color: Colors.white.withValues(alpha: 0.06)),
      ),
      child: InkWell(
        borderRadius: BorderRadius.circular(14),
        onTap: onView,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
          child: Row(children: [
            Container(
              width: 46, height: 46,
              decoration: BoxDecoration(
                  color: const Color(0xFF2D2335),
                  borderRadius: BorderRadius.circular(12)),
              child: Center(
                  child: Text(_siteEmoji(title),
                      style: const TextStyle(fontSize: 22))),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(children: [
                    Text(title,
                        style: const TextStyle(
                            color: AppColors.text,
                            fontSize: 15,
                            fontWeight: FontWeight.bold)),
                    if (isFav) ...[
                      const SizedBox(width: 4),
                      const Text('★',
                          style: TextStyle(
                              color: Color(0xFFF59E0B), fontSize: 14)),
                    ],
                  ]),
                  const SizedBox(height: 2),
                  Text(username,
                      style: const TextStyle(
                          color: AppColors.textSub, fontSize: 12),
                      overflow: TextOverflow.ellipsis),
                  Builder(builder: (context) {
                    final cat = _getCategory(title);
                    if (cat == null) return const SizedBox.shrink();
                    return Padding(
                      padding: const EdgeInsets.only(top: 3),
                      child: Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 6, vertical: 1),
                        decoration: BoxDecoration(
                          color: const Color(0xFF7A2BBF)
                              .withValues(alpha: 0.12),
                          borderRadius: BorderRadius.circular(4),
                          border: Border.all(
                              color: const Color(0xFF7A2BBF)
                                  .withValues(alpha: 0.25)),
                        ),
                        child: Text('${cat.$2} ${cat.$1}',
                            style: const TextStyle(
                                color: Color(0xFFa78bfa), fontSize: 10)),
                      ),
                    );
                  }),
                ],
              ),
            ),
            if (inTrash) ...[
              _action('Geri Al', onRestore, color: AppColors.success),
              const SizedBox(width: 6),
              _action('Sil', onDelete, color: AppColors.danger),
            ] else ...[
              _action(isFav ? '★' : '☆', onFav,
                  color: const Color(0xFFF59E0B)),
              const SizedBox(width: 4),
              _action('Kopyala', onCopy),
              const SizedBox(width: 4),
              _action('Düzenle', onEdit),
              const SizedBox(width: 4),
              _action('Sil', onTrash, color: AppColors.danger),
            ],
          ]),
        ),
      ),
    );
  }

  Widget _action(String label, VoidCallback onTap, {Color? color}) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
        decoration: BoxDecoration(
          color: (color ?? AppColors.textSub).withValues(alpha: 0.15),
          borderRadius: BorderRadius.circular(6),
          border: Border.all(
              color: (color ?? AppColors.textSub).withValues(alpha: 0.3)),
        ),
        child: Text(label,
            style: TextStyle(
                color: color ?? AppColors.textSub,
                fontSize: 11,
                fontWeight: FontWeight.w600)),
      ),
    );
  }
}

// ── Detay Diyaloğu ───────────────────────────────────────────────────────────

class _DetailDialog extends StatefulWidget {
  final Map<String, dynamic> entry;
  final Future<String> Function(int id) passwordFetcher;

  const _DetailDialog({required this.entry, required this.passwordFetcher});

  @override
  State<_DetailDialog> createState() => _DetailDialogState();
}

class _DetailDialogState extends State<_DetailDialog> {
  String? _pwd;
  bool _visible = false;

  @override
  void initState() {
    super.initState();
    _loadPwd();
  }

  Future<void> _loadPwd() async {
    try {
      final p = await widget.passwordFetcher(
          (widget.entry['id'] as num).toInt());
      if (mounted) setState(() => _pwd = p);
    } catch (_) {}
  }

  @override
  Widget build(BuildContext context) {
    final e = widget.entry;
    return AlertDialog(
      backgroundColor: const Color(0xFF171717),
      title: Row(children: [
        Text(_siteEmoji(e['title'] ?? ''),
            style: const TextStyle(fontSize: 28)),
        const SizedBox(width: 10),
        Expanded(
          child: Text(e['title'] ?? '',
              style: const TextStyle(
                  color: AppColors.text,
                  fontSize: 18,
                  fontWeight: FontWeight.bold)),
        ),
      ]),
      content: SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            _field('Kullanıcı Adı', e['username'] ?? ''),
            const SizedBox(height: 12),
            _pwdField(),
            if ((e['url'] as String? ?? '').isNotEmpty) ...[
              const SizedBox(height: 12),
              _field('URL', e['url'] ?? ''),
            ],
            if ((e['notes'] as String? ?? '').isNotEmpty) ...[
              const SizedBox(height: 12),
              _field('Notlar', e['notes'] ?? '', multiline: true),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Kapat',
              style: TextStyle(color: AppColors.accentL)),
        ),
      ],
    );
  }

  Widget _field(String label, String value, {bool multiline = false}) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label,
            style: const TextStyle(color: AppColors.textSub, fontSize: 11)),
        const SizedBox(height: 4),
        Row(children: [
          Expanded(
              child: Text(value,
                  style: const TextStyle(color: AppColors.text, fontSize: 14),
                  maxLines: multiline ? 4 : 1,
                  overflow: TextOverflow.ellipsis)),
          IconButton(
            icon: const Icon(Icons.copy, color: AppColors.textSub, size: 18),
            padding: EdgeInsets.zero,
            onPressed: () => Clipboard.setData(ClipboardData(text: value)),
          ),
        ]),
      ],
    );
  }

  Widget _pwdField() {
    final pwd = _pwd;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('Şifre',
            style: TextStyle(color: AppColors.textSub, fontSize: 11)),
        const SizedBox(height: 4),
        Row(children: [
          Expanded(
            child: Text(
              pwd == null
                  ? '...'
                  : (_visible ? pwd : '•' * pwd.length.clamp(8, 20)),
              style: const TextStyle(
                  color: AppColors.text, fontSize: 14, letterSpacing: 1),
            ),
          ),
          IconButton(
            icon: Icon(
                _visible ? Icons.visibility_off : Icons.visibility,
                color: AppColors.textSub,
                size: 18),
            padding: EdgeInsets.zero,
            onPressed: () => setState(() => _visible = !_visible),
          ),
          if (pwd != null)
            IconButton(
              icon: const Icon(Icons.copy, color: AppColors.textSub, size: 18),
              padding: EdgeInsets.zero,
              onPressed: () => Clipboard.setData(ClipboardData(text: pwd)),
            ),
        ]),
      ],
    );
  }
}

// ── Ekle / Düzenle Formu ──────────────────────────────────────────────────────

class _PasswordForm extends StatefulWidget {
  final Map<String, dynamic>? initial;
  final Future<void> Function(Map<String, String>) onSave;

  const _PasswordForm({this.initial, required this.onSave});

  @override
  State<_PasswordForm> createState() => _PasswordFormState();
}

class _PasswordFormState extends State<_PasswordForm> {
  late final TextEditingController _title, _user, _pwd, _url, _notes;
  final _form = GlobalKey<FormState>();
  bool _saving = false;
  bool _pwdVisible = false;

  @override
  void initState() {
    super.initState();
    final i = widget.initial;
    _title = TextEditingController(text: i?['title']    as String? ?? '');
    _user  = TextEditingController(text: i?['username'] as String? ?? '');
    _pwd   = TextEditingController(text: i?['password'] as String? ?? '');
    _url   = TextEditingController(text: i?['url']      as String? ?? '');
    _notes = TextEditingController(text: i?['notes']    as String? ?? '');
  }

  @override
  void dispose() {
    for (final c in [_title, _user, _pwd, _url, _notes]) c.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (!_form.currentState!.validate()) return;
    setState(() => _saving = true);
    try {
      await widget.onSave({
        'title': _title.text.trim(), 'username': _user.text.trim(),
        'password': _pwd.text, 'url': _url.text.trim(),
        'notes': _notes.text.trim(),
      });
      if (mounted) Navigator.pop(context);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
                content: Text('Hata: $e'),
                backgroundColor: AppColors.danger));
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(
        left: 20, right: 20, top: 20,
        bottom: MediaQuery.of(context).viewInsets.bottom + 20,
      ),
      child: Form(
        key: _form,
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Text(
            widget.initial == null ? 'Yeni Şifre Ekle' : 'Şifreyi Düzenle',
            style: const TextStyle(
                color: AppColors.text,
                fontSize: 18,
                fontWeight: FontWeight.bold),
          ),
          const SizedBox(height: 16),
          _tf(_title, 'Başlık *', Icons.label_outline,
              validator: (v) =>
                  (v == null || v.trim().isEmpty) ? 'Gerekli' : null),
          const SizedBox(height: 10),
          _tf(_user, 'Kullanıcı Adı *', Icons.person_outline,
              validator: (v) =>
                  (v == null || v.trim().isEmpty) ? 'Gerekli' : null),
          const SizedBox(height: 10),
          TextFormField(
            controller: _pwd,
            obscureText: !_pwdVisible,
            style: const TextStyle(color: AppColors.text),
            decoration: InputDecoration(
              labelText: 'Şifre *',
              prefixIcon: const Icon(Icons.lock_outline,
                  color: AppColors.textSub, size: 20),
              suffixIcon: IconButton(
                icon: Icon(
                    _pwdVisible ? Icons.visibility_off : Icons.visibility,
                    color: AppColors.textSub,
                    size: 20),
                onPressed: () =>
                    setState(() => _pwdVisible = !_pwdVisible),
              ),
            ),
            validator: (v) =>
                (v == null || v.isEmpty) ? 'Gerekli' : null,
          ),
          const SizedBox(height: 10),
          _tf(_url,   'URL (opsiyonel)',    Icons.link),
          const SizedBox(height: 10),
          _tf(_notes, 'Notlar (opsiyonel)', Icons.notes, maxLines: 2),
          const SizedBox(height: 20),
          SizedBox(
            width: double.infinity,
            child: ElevatedButton(
              onPressed: _saving ? null : _save,
              child: _saving
                  ? const SizedBox(
                      height: 20, width: 20,
                      child: CircularProgressIndicator(
                          strokeWidth: 2, color: Colors.white))
                  : const Text('Kaydet'),
            ),
          ),
        ]),
      ),
    );
  }

  Widget _tf(TextEditingController c, String label, IconData icon,
      {int maxLines = 1, String? Function(String?)? validator}) {
    return TextFormField(
      controller: c,
      maxLines: maxLines,
      style: const TextStyle(color: AppColors.text),
      decoration: InputDecoration(
        labelText: label,
        prefixIcon: Icon(icon, color: AppColors.textSub, size: 20),
      ),
      validator: validator,
    );
  }
}
