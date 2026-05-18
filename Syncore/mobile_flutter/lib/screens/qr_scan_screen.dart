import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import '../app_theme.dart';
import '../services/storage_service.dart';

/// QR tarama ekranı.
/// pvault://{ip}:8765?secret={b64} formatını parse eder.
class QRScanScreen extends StatefulWidget {
  const QRScanScreen({super.key});

  @override
  State<QRScanScreen> createState() => _QRScanScreenState();
}

class _QRScanScreenState extends State<QRScanScreen> {
  final _controller = MobileScannerController(
    detectionSpeed: DetectionSpeed.noDuplicates,
    facing: CameraFacing.back,
  );

  bool _detected = false;
  bool _hasSaved = false;

  String? _pendingUsername;
  String? _pendingPwdB64;

  @override
  void initState() {
    super.initState();
    _checkSaved();
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final args = ModalRoute.of(context)?.settings.arguments as Map?;
    if (args != null) {
      _pendingUsername = args['pendingUsername'] as String?;
      _pendingPwdB64   = args['pendingPwdB64']   as String?;
    }
  }

  Future<void> _checkSaved() async {
    final saved = await StorageService.load();
    if (mounted) setState(() => _hasSaved = saved?.serverIp != null);
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _onDetect(BarcodeCapture capture) {
    if (_detected) return;
    final raw = capture.barcodes.firstOrNull?.rawValue;
    if (raw == null) return;

    final ip = _parseQr(raw);
    if (ip == null) return;

    _detected = true;
    _controller.stop();
    StorageService.saveServerIp(ip).then((_) async {
      if (!mounted) return;

      String? username = _pendingUsername;
      String? pwdB64   = _pendingPwdB64;

      if (username == null || pwdB64 == null) {
        // AppBar'dan açıldı — kayıtlı credentials kullan
        final creds = await StorageService.load();
        if (!mounted) return;
        if (creds == null) {
          Navigator.pushReplacementNamed(context, '/');
          return;
        }
        username = creds.username;
        pwdB64   = creds.passwordSha256B64;
      }

      Navigator.pushNamed(context, '/auth', arguments: {
        'ip':               ip,
        'username':         username,
        'passwordSha256B64': pwdB64,
        'saveCreds':        _pendingUsername != null,  // auth başarılıysa kaydet
      });
    });
  }

  /// pvault://{ip}:8765 veya pvault://{ip}:8765?user={username} → ip veya null
  static String? _parseQr(String data) {
    try {
      final uri = Uri.parse(data);
      if (uri.scheme != 'pvault') return null;
      final ip = uri.host;
      return ip.isEmpty ? null : ip;
    } catch (_) {
      return null;
    }
  }

  void _useSaved() async {
    final saved = await StorageService.load();
    if (saved == null || !mounted) return;
    if (saved.serverIp == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Kayıtlı sunucu IP bulunamadı. QR okutun.')),
      );
      return;
    }
    Navigator.pushNamed(context, '/auth', arguments: {
      'ip':               saved.serverIp!,
      'username':         saved.username,
      'passwordSha256B64': saved.passwordSha256B64,
    });
  }

  Future<void> _onLogout() async {
    await StorageService.clear();
    if (!mounted) return;
    Navigator.pushNamedAndRemoveUntil(context, '/', (_) => false);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        automaticallyImplyLeading: false,
        title: const Text('Syncore'),
        actions: [
          TextButton.icon(
            onPressed: _onLogout,
            icon: const Icon(Icons.logout, size: 18, color: Color(0xFFEF4444)),
            label: const Text('Çıkış', style: TextStyle(color: Color(0xFFEF4444), fontSize: 13)),
          ),
        ],
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
          child: Column(
            children: [
              const Text(
                'Kamerayı PC ekranındaki QR koda tutun',
                style: TextStyle(color: AppColors.textSub, fontSize: 14),
              ),
              const SizedBox(height: 16),

              // Kamera — mobile_scanner native render, rotasyon sorunu yok
              Expanded(
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(16),
                  child: MobileScanner(
                    controller: _controller,
                    onDetect: _onDetect,
                    errorBuilder: (context, error, child) {
                      return _CameraError(error: error.errorCode.name);
                    },
                  ),
                ),
              ),
              const SizedBox(height: 16),

              // Tarama durumu
              Text(
                _detected ? '✅  QR bulundu, bağlanıyor...' : '🔍  QR aranıyor...',
                style: TextStyle(
                  color: _detected ? AppColors.success : AppColors.textSub,
                  fontSize: 13,
                ),
              ),
              const SizedBox(height: 12),

              // Butonlar
              Row(
                children: [
                  Expanded(
                    child: _PvButton(
                      label: '⌨  Manuel Giriş',
                      color: AppColors.surface,
                      onTap: () => Navigator.pushNamed(context, '/manual'),
                    ),
                  ),
                ],
              ),
              if (_hasSaved) ...[
                const SizedBox(height: 10),
                _PvButton(
                  label: '🔄  Kayıtlı Bağlantıyı Kullan',
                  color: const Color(0xFF26183A),
                  onTap: _useSaved,
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

// ── Yardımcı widget'lar ──────────────────────────────────────────────────────

class _CameraError extends StatelessWidget {
  final String error;
  const _CameraError({required this.error});

  @override
  Widget build(BuildContext context) {
    return Container(
      color: AppColors.surface,
      child: Center(
        child: Text(
          '❌  Kamera hatası: $error\nManuel giriş kullanın.',
          style: const TextStyle(color: AppColors.danger, fontSize: 14),
          textAlign: TextAlign.center,
        ),
      ),
    );
  }
}

class _PvButton extends StatelessWidget {
  final String label;
  final Color color;
  final VoidCallback onTap;

  const _PvButton({
    required this.label,
    required this.color,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: double.infinity,
      child: ElevatedButton(
        onPressed: onTap,
        style: ElevatedButton.styleFrom(
          backgroundColor: color,
          foregroundColor: AppColors.text,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
          padding: const EdgeInsets.symmetric(vertical: 14),
        ),
        child: Text(label, style: const TextStyle(fontSize: 15)),
      ),
    );
  }
}
