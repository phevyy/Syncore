"""
Password Vault - Desktop Application
=====================================
Akış A (desktop-first, Argon2 vault):
  Login → QR (TFA) → Mobil QR tarar → Vault açılır
Akış B (mobile-first, SHA-256 vault):
  Desktop başlar → TFA gösterilir → Mobil bağlanır → Vault oluşturulur/açılır
"""

import sys
import socket
import base64

from PyQt6.QtWidgets import QApplication, QMessageBox, QSplashScreen
from PyQt6.QtGui import QPixmap, QIcon, QPainter, QLinearGradient, QColor
from PyQt6.QtCore import QTimer, QObject, pyqtSignal, Qt

from ui.login_window import LoginWindow
from ui.tfa_waiting_window import TFAWaitingWindow
from ui.manager_window import ManagerWindow
from ui.styles import get_complete_style
from network_server import NetworkServer
from session_manager import load_session, clear_session, save_session_v2
from vault_storage import VaultStorage
from pathlib import Path


def _asset(relative: str) -> Path:
    """PyInstaller frozen ve normal mod için asset yolu."""
    if getattr(sys, 'frozen', False):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).parent
    return base / relative


class PasswordVaultApp(QObject):
    # (success, device_id, username, secret_b64)
    _auth_result = pyqtSignal(bool, int, str, str)

    def __init__(self):
        super().__init__()
        self.app = QApplication(sys.argv)
        self.app.setApplicationName('Syncore')
        self.app.setStyleSheet(get_complete_style())

        icon_path = _asset('assets/icon/logo.ico')
        if icon_path.exists():
            self.app.setWindowIcon(QIcon(str(icon_path)))

        self.login_window   = None
        self.tfa_window     = None
        self.manager_window = None
        self.vault          = None
        self.network_server = None
        self.shared_secret  = None
        self._paired_device_id: int = 0

        self._auth_result.connect(self._handle_auth_result)

    def run(self):
        # Splash ekranı
        splash_path = _asset('assets/splash/splash.png')
        splash = None
        if splash_path.exists():
            logo = QPixmap(str(splash_path))
            screen = self.app.primaryScreen()
            geo = screen.availableGeometry() if screen else None
            sw = geo.width()  if geo else 900
            sh = geo.height() if geo else 600

            # Manager window ile aynı boyut
            pw, ph = 1000, 680

            bg = QPixmap(pw, ph)
            painter = QPainter(bg)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            grad = QLinearGradient(0, 0, 0, ph)
            grad.setColorAt(0.0, QColor('#0A0A0A'))
            grad.setColorAt(0.45, QColor('#1a0a2e'))
            grad.setColorAt(1.0, QColor('#0A0A0A'))
            painter.fillRect(0, 0, pw, ph, grad)

            # Logoyu ortala (%50 pencere)
            if not logo.isNull():
                max_w = int(pw * 0.50)
                max_h = int(ph * 0.50)
                scaled = logo.scaled(
                    max_w, max_h,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                x = (pw - scaled.width())  // 2
                y = (ph - scaled.height()) // 2
                painter.drawPixmap(x, y, scaled)
            painter.end()

            splash = QSplashScreen(bg, Qt.WindowType.WindowStaysOnTopHint)
            splash.show()
            self.app.processEvents()

        def _start():
            if splash:
                splash.close()
            vault = self._try_auto_login()
            if vault:
                self.on_login_success(vault)
            else:
                session = load_session()
                if session:
                    self.login_window = LoginWindow()
                    self.login_window.login_success.connect(self.on_login_success)
                    self.login_window.show()
                else:
                    self._show_mobile_first_tfa()

        QTimer.singleShot(2500, _start)
        return self.app.exec()

    def _try_auto_login(self):
        """Kayıtlı oturumla vault'u açmayı dener."""
        session = load_session()
        if not session:
            return None
        username = session['username']

        if session['format'] == 'v2':
            # SHA-256 tabanlı vault (mobile-first)
            try:
                secret_b64 = session['secret_b64']
                network_secret = base64.b64decode(secret_b64)
                db_path = VaultStorage.get_user_db_path(username)
                vault = VaultStorage(db_path)
                if vault.unlock_or_create_with_network_secret(username, network_secret):
                    return vault
            except Exception:
                pass
        else:
            # Argon2 tabanlı vault (desktop-first)
            password = session.get('password', '')
            if not password:
                return None
            try:
                db_path = VaultStorage.get_user_db_path(username)
                vault = VaultStorage(db_path)
                if vault.is_initialized() and vault.unlock_vault(username, password):
                    return vault
            except Exception:
                pass
            # Migration: eski tek-kullanıcı vault.db
            try:
                import shutil
                old_path = str(Path.home() / ".password_vault" / "vault.db")
                old_vault = VaultStorage(old_path)
                if old_vault.is_initialized() and old_vault.unlock_vault(username, password):
                    new_path = VaultStorage.get_user_db_path(username)
                    shutil.copy2(old_path, new_path)
                    vault = VaultStorage(new_path)
                    vault.unlock_vault(username, password)
                    return vault
            except Exception:
                pass

        clear_session()
        return None

    def _get_server_ip(self) -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return '127.0.0.1'

    # ── Mobile-first TFA (oturum yok) ────────────────────────────────────

    def _show_mobile_first_tfa(self):
        """Önceki oturum yok → doğrudan TFA; mobil kullanıcı adını belirler."""
        server_ip = self._get_server_ip()

        self.network_server = NetworkServer()
        self.network_server.start()

        def on_auth_result(success, device_id, username, secret_b64):
            self._auth_result.emit(success, device_id, username, secret_b64)

        # shared_secret=None → TOFU: ilk mobilin password_hash'ini kullan
        self.network_server.set_auto_challenge(None, on_auth_result, expected_username=None)

        self.tfa_window = TFAWaitingWindow(
            server_ip=server_ip,
            username='Mobil ile giriş yapın',
        )
        self.tfa_window.approved.connect(self.on_2fa_approved)
        self.tfa_window.cancelled.connect(self.on_2fa_cancelled)
        self.tfa_window.timeout.connect(self.on_2fa_timeout)
        self.tfa_window.show()

    # ── Desktop-first akış ────────────────────────────────────────────────

    def on_login_success(self, vault):
        """Desktop login / auto-login → vault hazır → TFA ekranı."""
        self.vault = vault
        server_ip  = self._get_server_ip()
        self.shared_secret = vault.get_network_secret()
        username   = vault.get_username()

        self.network_server = NetworkServer()
        self.network_server.start()

        def on_auth_result(success, device_id, actual_username, actual_secret_b64):
            self._auth_result.emit(success, device_id, actual_username, actual_secret_b64)

        # shared_secret=None, expected_username=None: tam TOFU — her kullanıcı bağlanabilir
        self.network_server.set_auto_challenge(
            None, on_auth_result, expected_username=None
        )

        self.tfa_window = TFAWaitingWindow(server_ip=server_ip, username='')
        self.tfa_window.approved.connect(self.on_2fa_approved)
        self.tfa_window.cancelled.connect(self.on_2fa_cancelled)
        self.tfa_window.timeout.connect(self.on_2fa_timeout)
        self.tfa_window.show()

    # ── Auth sonucu ───────────────────────────────────────────────────────

    def _handle_auth_result(self, success: bool, device_id: int,
                             username: str, secret_b64: str):
        if not self.tfa_window or not self.tfa_window.isVisible():
            return
        if not success:
            QMessageBox.warning(
                self.tfa_window, '2FA Başarısız',
                'Mobil cihazdan yanlış yanıt geldi. Tekrar deneyin.'
            )
            return

        # Her zaman authenticated username'in vault'unu aç/oluştur.
        # Mevcut vault farklı kullanıcıya aitse değiştir.
        current_user = self.vault.get_username() if self.vault else ''
        if username and secret_b64:
            try:
                network_secret = base64.b64decode(secret_b64)
                db_path = VaultStorage.get_user_db_path(username)
                new_vault = VaultStorage(db_path)
                if new_vault.unlock_or_create_with_network_secret(username, network_secret):
                    # SHA-256 vault (yeni veya mevcut)
                    self.vault         = new_vault
                    self.shared_secret = network_secret
                    save_session_v2(username, secret_b64)
                elif current_user == username and self.vault is not None:
                    # Argon2 vault zaten yüklü ve doğru kullanıcıya ait — devam
                    pass
                else:
                    QMessageBox.warning(self.tfa_window, 'Hata',
                                        'Vault açılamadı veya kullanıcı doğrulanamadı.')
                    return
            except Exception as e:
                QMessageBox.critical(self.tfa_window, 'Hata', str(e))
                return

        if self.vault:
            self.tfa_window.on_approve()
        else:
            QMessageBox.warning(self.tfa_window, 'Hata', 'Vault yüklenemedi.')

    def on_2fa_approved(self):
        if self.tfa_window:
            self.tfa_window.close()
        self._stop_server()
        self.manager_window = ManagerWindow(self.vault)
        self.manager_window.logout_requested.connect(self._on_manager_logout)
        self.manager_window.show()

    def _on_manager_logout(self):
        self.vault = None
        self.manager_window = None
        self._show_mobile_first_tfa()

    def on_2fa_cancelled(self):
        self._stop_server()
        self.vault = None
        if self.login_window:
            self.login_window.show()
        else:
            self._show_mobile_first_tfa()

    def on_2fa_timeout(self):
        if self.tfa_window:
            self.tfa_window.close()
        self._stop_server()
        self.vault = None
        QMessageBox.warning(None, 'Zaman Aşımı', '2FA onayı alınamadı!')
        if self.login_window:
            self.login_window.show()
        else:
            self._show_mobile_first_tfa()

    def _stop_server(self):
        if self.network_server:
            try:
                self.network_server.stop()
            except Exception:
                pass
            self.network_server = None


if __name__ == '__main__':
    app = PasswordVaultApp()
    sys.exit(app.run())
