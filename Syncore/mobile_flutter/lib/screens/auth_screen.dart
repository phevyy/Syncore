import 'package:flutter/material.dart';
import '../app_theme.dart';
import '../services/auth_service.dart';
import '../services/storage_service.dart';

/// Bağlantı & doğrulama ekranı.
/// Argümanlar: {'ip': String, 'secret': String}
class AuthScreen extends StatefulWidget {
  const AuthScreen({super.key});

  @override
  State<AuthScreen> createState() => _AuthScreenState();
}

class _AuthScreenState extends State<AuthScreen> {
  _State _state = _State.connecting;
  String? _errorMsg;
  String? _ip;

  String? _username;
  String? _passwordSha256B64;
  bool    _saveCreds = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final args = ModalRoute.of(context)?.settings.arguments as Map?;
    if (args != null && _ip == null) {
      _ip                = args['ip']               as String;
      _username          = args['username']          as String;
      _passwordSha256B64 = args['passwordSha256B64'] as String;
      _saveCreds         = args['saveCreds']         as bool? ?? false;
      _doAuth();
    }
  }

  Future<void> _doAuth() async {
    setState(() { _state = _State.connecting; _errorMsg = null; });
    final result = await AuthService.authenticate(
      serverIp:          _ip!,
      username:          _username!,
      passwordSha256B64: _passwordSha256B64!,
    );
    if (!mounted) return;
    if (result.success) {
      if (_saveCreds) {
        await StorageService.saveCredentials(_username!, _passwordSha256B64!);
      }
      await StorageService.saveServerIp(_ip!);
      if (!mounted) return;
      setState(() => _state = _State.success);
      Future.delayed(const Duration(milliseconds: 800), () {
        if (!mounted) return;
        if (_saveCreds) {
          // İlk kayıt → yeni vault ekranı aç
          Navigator.pushNamedAndRemoveUntil(context, '/vault', (_) => false);
        } else {
          // Zaten vault'taydık → geri pop et, _scanQr devam etsin
          Navigator.popUntil(context, ModalRoute.withName('/vault'));
        }
      });
    } else {
      setState(() {
        _state    = _State.error;
        _errorMsg = result.errorMessage;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('2FA Doğrulama'),
        leading: BackButton(
          onPressed: () => Navigator.popUntil(context, ModalRoute.withName('/scan')),
        ),
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              // İkon
              Text(
                _state.icon,
                style: const TextStyle(fontSize: 72),
              ),
              const SizedBox(height: 24),

              // Başlık
              Text(
                _state.title,
                style: TextStyle(
                  color: _state.color,
                  fontSize: 22,
                  fontWeight: FontWeight.bold,
                ),
              ),
              const SizedBox(height: 12),

              // Mesaj
              Text(
                _state == _State.connecting
                    ? 'PC ($_ip) ile güvenli bağlantı kuruluyor...'
                    : _state == _State.success
                        ? "PC'deki şifre kasanız açıldı.\nBu ekranı kapatabilirsiniz."
                        : _errorMsg ?? 'Bilinmeyen hata',
                style: TextStyle(
                  color: _state == _State.error
                      ? AppColors.warn
                      : AppColors.textSub,
                  fontSize: 14,
                ),
                textAlign: TextAlign.center,
              ),

              if (_state == _State.connecting) ...[
                const SizedBox(height: 32),
                const CircularProgressIndicator(
                  color: AppColors.accent,
                  strokeWidth: 3,
                ),
              ],

              if (_state == _State.success) ...[
                const SizedBox(height: 16),
                const Text(
                  'Şifreler ekranına yönlendiriliyorsunuz...',
                  style: TextStyle(color: AppColors.textSub, fontSize: 13),
                ),
              ],

              if (_state == _State.error) ...[
                const SizedBox(height: 32),
                SizedBox(
                  width: double.infinity,
                  child: ElevatedButton(
                    onPressed: _doAuth,
                    child: const Text('🔄  Tekrar Dene'),
                  ),
                ),
                const SizedBox(height: 12),
                SizedBox(
                  width: double.infinity,
                  child: ElevatedButton(
                    onPressed: () =>
                        Navigator.popUntil(context, ModalRoute.withName('/scan')),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: AppColors.surface,
                    ),
                    child: const Text('← Geri Dön'),
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

enum _State {
  connecting('🔄', 'Bağlanıyor...',       AppColors.textSub),
  success   ('✅', 'Vault Açıldı!',       AppColors.success),
  error     ('❌', 'Doğrulama Başarısız', AppColors.danger);

  final String icon;
  final String title;
  final Color  color;
  const _State(this.icon, this.title, this.color);
}
