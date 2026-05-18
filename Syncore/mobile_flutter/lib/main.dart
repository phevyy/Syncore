import 'package:flutter/material.dart';
import 'app_theme.dart';
import 'services/storage_service.dart';
import 'screens/login_screen.dart';
import 'screens/qr_scan_screen.dart';
import 'screens/manual_screen.dart';
import 'screens/auth_screen.dart';
import 'screens/vault_screen.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final hasCredentials = await StorageService.hasCredentials();
  runApp(PasswordVaultApp(hasCredentials: hasCredentials));
}

class PasswordVaultApp extends StatelessWidget {
  final bool hasCredentials;
  const PasswordVaultApp({super.key, required this.hasCredentials});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Syncore',
      debugShowCheckedModeBanner: false,
      theme: buildAppTheme(),
      initialRoute: hasCredentials ? '/vault' : '/',
      routes: {
        '/':       (_) => const LoginScreen(),
        '/scan':   (_) => const QRScanScreen(),
        '/manual': (_) => const ManualScreen(),
        '/auth':   (_) => const AuthScreen(),
        '/vault':  (_) => const VaultScreen(),
      },
    );
  }
}
