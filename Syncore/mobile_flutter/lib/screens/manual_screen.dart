import 'package:flutter/material.dart';
import '../app_theme.dart';
import '../services/storage_service.dart';

/// Manuel IP giriş ekranı (QR taranamadığında).
class ManualScreen extends StatefulWidget {
  const ManualScreen({super.key});

  @override
  State<ManualScreen> createState() => _ManualScreenState();
}

class _ManualScreenState extends State<ManualScreen> {
  final _ipCtrl   = TextEditingController();
  final _formKey  = GlobalKey<FormState>();
  String? _error;

  @override
  void initState() {
    super.initState();
    _loadSavedIp();
  }

  Future<void> _loadSavedIp() async {
    final saved = await StorageService.load();
    if (saved?.serverIp != null && mounted) {
      _ipCtrl.text = saved!.serverIp!;
    }
  }

  @override
  void dispose() {
    _ipCtrl.dispose();
    super.dispose();
  }

  void _connect() async {
    if (!_formKey.currentState!.validate()) return;
    final ip = _ipCtrl.text.trim();

    final creds = await StorageService.load();
    if (creds == null) {
      setState(() => _error = 'Önce giriş yapın.');
      return;
    }

    await StorageService.saveServerIp(ip);
    if (!mounted) return;
    Navigator.pushNamed(context, '/auth', arguments: {
      'ip':               ip,
      'username':         creds.username,
      'passwordSha256B64': creds.passwordSha256B64,
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Manuel Bağlantı'),
        leading: BackButton(onPressed: () => Navigator.pop(context)),
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Form(
            key: _formKey,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'PC\'nin IP adresini girin',
                  style: TextStyle(color: AppColors.textSub, fontSize: 14),
                ),
                const SizedBox(height: 24),

                TextFormField(
                  controller: _ipCtrl,
                  style: const TextStyle(color: AppColors.text),
                  decoration: const InputDecoration(
                    labelText: 'Server IP',
                    hintText: '192.168.1.100',
                    prefixIcon: Icon(Icons.computer, color: AppColors.textSub),
                  ),
                  keyboardType: TextInputType.number,
                  validator: (v) =>
                      (v == null || v.trim().isEmpty) ? 'IP adresi gerekli' : null,
                ),

                if (_error != null) ...[
                  const SizedBox(height: 12),
                  Text(_error!, style: const TextStyle(color: AppColors.danger)),
                ],

                const Spacer(),

                SizedBox(
                  width: double.infinity,
                  child: ElevatedButton(
                    onPressed: _connect,
                    child: const Text('Bağlan'),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
