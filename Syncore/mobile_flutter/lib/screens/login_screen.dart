import 'dart:convert';
import 'package:crypto/crypto.dart';
import 'package:flutter/material.dart';
import '../app_theme.dart';
import '../services/storage_service.dart';

/// Giriş Yap / Kayıt Ol ekranı.
/// Kimlik bilgileri yerel olarak SHA-256 hash ile saklanır.
class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen>
    with SingleTickerProviderStateMixin {
  late final TabController _tabs;

  final _loginFormKey    = GlobalKey<FormState>();
  final _registerFormKey = GlobalKey<FormState>();

  final _loginUserCtrl   = TextEditingController();
  final _loginPwdCtrl    = TextEditingController();
  final _regUserCtrl     = TextEditingController();
  final _regPwdCtrl      = TextEditingController();
  final _regConfirmCtrl  = TextEditingController();

  bool _loginPwdVisible  = false;
  bool _regPwdVisible    = false;
  bool _loading          = false;
  bool _hasAccount       = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _tabs = TabController(length: 2, vsync: this);
    _tabs.addListener(() => setState(() => _error = null));
    _checkExistingCredentials();
  }

  Future<void> _checkExistingCredentials() async {
    final has = await StorageService.hasCredentials();
    if (mounted) {
      setState(() => _hasAccount = has);
      if (has) _tabs.animateTo(0);
    }
  }

  @override
  void dispose() {
    _tabs.dispose();
    _loginUserCtrl.dispose();
    _loginPwdCtrl.dispose();
    _regUserCtrl.dispose();
    _regPwdCtrl.dispose();
    _regConfirmCtrl.dispose();
    super.dispose();
  }

  String _sha256B64(String password) {
    final bytes = utf8.encode(password);
    final digest = sha256.convert(bytes);
    return base64.encode(digest.bytes);
  }

  Future<void> _onLogin() async {
    if (!_loginFormKey.currentState!.validate()) return;
    setState(() { _loading = true; _error = null; });

    try {
      final username    = _loginUserCtrl.text.trim();
      final enteredHash = _sha256B64(_loginPwdCtrl.text.trim());
      final saved       = await StorageService.load();

      if (saved != null &&
          saved.username.toLowerCase() == username.toLowerCase() &&
          saved.passwordSha256B64 == enteredHash) {
        // Yerel kayıt eşleşiyor → direkt vault
        if (!mounted) return;
        Navigator.pushReplacementNamed(context, '/vault');
      } else {
        // Yerel kayıt yok veya eşleşmiyor → desktop'tan doğrula (QR ile)
        if (!mounted) return;
        Navigator.pushNamed(context, '/scan', arguments: {
          'pendingUsername': username,
          'pendingPwdB64':   enteredHash,
        });
      }
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _deleteAccount() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        backgroundColor: const Color(0xFF171717),
        title: const Text('Hesabı Sil', style: TextStyle(color: Color(0xFFEF4444))),
        content: const Text(
          'Kayıtlı kimlik bilgileri ve bağlantı bilgileri silinecek.\nBu işlem geri alınamaz.',
          style: TextStyle(color: Color(0xFFAF99C2)),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('İptal'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Sil', style: TextStyle(color: Color(0xFFEF4444))),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    await StorageService.clear();
    if (!mounted) return;
    setState(() { _hasAccount = false; _error = null; });
    _loginUserCtrl.clear();
    _loginPwdCtrl.clear();
    _tabs.animateTo(1); // Kayıt Ol sekmesine geç
  }

  void _onRegister() {
    if (!_registerFormKey.currentState!.validate()) return;
    final username = _regUserCtrl.text.trim();
    final pwdHash  = _sha256B64(_regPwdCtrl.text.trim());
    Navigator.pushNamed(context, '/scan', arguments: {
      'pendingUsername': username,
      'pendingPwdB64':   pwdHash,
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 28, vertical: 24),
          child: Column(
            children: [
              const SizedBox(height: 24),

              // İkon
              Container(
                width: 80, height: 80,
                decoration: BoxDecoration(
                  color: AppColors.surface,
                  borderRadius: BorderRadius.circular(20),
                  border: Border.all(color: AppColors.accent.withValues(alpha: 0.6), width: 1.5),
                ),
                child: const Center(
                  child: Text('🔐', style: TextStyle(fontSize: 38)),
                ),
              ),
              const SizedBox(height: 16),

              const Text(
                'Syncore',
                style: TextStyle(
                  color: AppColors.text,
                  fontSize: 24,
                  fontWeight: FontWeight.bold,
                ),
              ),
              const SizedBox(height: 24),

              // Sekme çubuğu
              Container(
                decoration: BoxDecoration(
                  color: AppColors.surface,
                  borderRadius: BorderRadius.circular(12),
                ),
                child: TabBar(
                  controller: _tabs,
                  indicatorSize: TabBarIndicatorSize.tab,
                  indicator: BoxDecoration(
                    color: AppColors.accent,
                    borderRadius: BorderRadius.circular(10),
                  ),
                  labelColor: AppColors.text,
                  unselectedLabelColor: AppColors.textSub,
                  labelStyle: const TextStyle(fontWeight: FontWeight.w600, fontSize: 15),
                  tabs: const [Tab(text: 'Giriş Yap'), Tab(text: 'Kayıt Ol')],
                ),
              ),
              const SizedBox(height: 24),

              if (_error != null) ...[
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: AppColors.danger.withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: AppColors.danger.withValues(alpha: 0.4)),
                  ),
                  child: Row(children: [
                    const Icon(Icons.error_outline, color: AppColors.danger, size: 18),
                    const SizedBox(width: 8),
                    Expanded(child: Text(_error!, style: const TextStyle(color: AppColors.danger, fontSize: 13))),
                  ]),
                ),
                const SizedBox(height: 16),
              ],

              // Form içeriği
              Expanded(
                child: TabBarView(
                  controller: _tabs,
                  children: [_buildLoginForm(), _buildRegisterForm()],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildLoginForm() {
    return Form(
      key: _loginFormKey,
      child: Column(
        children: [
          _inputField(
            controller: _loginUserCtrl,
            label: 'Kullanıcı Adı',
            icon: Icons.person_outline,
            validator: (v) => (v == null || v.trim().isEmpty) ? 'Gerekli' : null,
          ),
          const SizedBox(height: 14),
          _inputField(
            controller: _loginPwdCtrl,
            label: 'Şifre',
            icon: Icons.lock_outline,
            obscure: !_loginPwdVisible,
            suffixIcon: IconButton(
              icon: Icon(_loginPwdVisible ? Icons.visibility_off : Icons.visibility,
                  color: AppColors.textSub, size: 20),
              onPressed: () => setState(() => _loginPwdVisible = !_loginPwdVisible),
            ),
            validator: (v) => (v == null || v.isEmpty) ? 'Gerekli' : null,
            onSubmit: (_) => _onLogin(),
          ),
          const SizedBox(height: 28),
          SizedBox(
            width: double.infinity,
            child: ElevatedButton(
              onPressed: _loading ? null : _onLogin,
              child: _loading
                  ? const SizedBox(height: 20, width: 20,
                      child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                  : const Text('Giriş Yap'),
            ),
          ),
          if (_hasAccount) ...[
            const SizedBox(height: 12),
            TextButton(
              onPressed: _deleteAccount,
              child: const Text(
                'Hesabı Sil',
                style: TextStyle(color: Color(0xFFEF4444), fontSize: 13),
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildRegisterForm() {
    return Form(
      key: _registerFormKey,
      child: Column(
        children: [
          _inputField(
            controller: _regUserCtrl,
            label: 'Kullanıcı Adı',
            icon: Icons.person_outline,
            validator: (v) => (v == null || v.trim().isEmpty) ? 'Gerekli' : null,
          ),
          const SizedBox(height: 14),
          _inputField(
            controller: _regPwdCtrl,
            label: 'Şifre (en az 8 karakter)',
            icon: Icons.lock_outline,
            obscure: !_regPwdVisible,
            suffixIcon: IconButton(
              icon: Icon(_regPwdVisible ? Icons.visibility_off : Icons.visibility,
                  color: AppColors.textSub, size: 20),
              onPressed: () => setState(() => _regPwdVisible = !_regPwdVisible),
            ),
            validator: (v) {
              if (v == null || v.isEmpty) return 'Gerekli';
              if (v.length < 8) return 'En az 8 karakter';
              return null;
            },
          ),
          const SizedBox(height: 14),
          _inputField(
            controller: _regConfirmCtrl,
            label: 'Şifre Tekrar',
            icon: Icons.lock_outline,
            obscure: true,
            validator: (v) => v != _regPwdCtrl.text ? 'Şifreler eşleşmiyor' : null,
            onSubmit: (_) => _onRegister(),
          ),
          const SizedBox(height: 28),
          SizedBox(
            width: double.infinity,
            child: ElevatedButton(
              onPressed: _onRegister,
              child: const Text('Kayıt Ol'),
            ),
          ),
        ],
      ),
    );
  }

  Widget _inputField({
    required TextEditingController controller,
    required String label,
    required IconData icon,
    bool obscure = false,
    Widget? suffixIcon,
    String? Function(String?)? validator,
    void Function(String)? onSubmit,
  }) {
    return TextFormField(
      controller: controller,
      obscureText: obscure,
      autocorrect: false,
      enableSuggestions: !obscure,
      style: const TextStyle(color: AppColors.text),
      onFieldSubmitted: onSubmit,
      decoration: InputDecoration(
        labelText: label,
        prefixIcon: Icon(icon, color: AppColors.textSub, size: 20),
        suffixIcon: suffixIcon,
      ),
      validator: validator,
    );
  }
}
