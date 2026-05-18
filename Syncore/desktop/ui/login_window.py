"""
Login Window - Kullanıcı Adı & Şifre ile Giriş / Kayıt (Çok Kullanıcı)
"""

import sys
import os
import shutil
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QMessageBox, QGraphicsDropShadowEffect
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vault_storage import VaultStorage
from session_manager import save_session
from ui.styles import COLORS, BUTTON_STYLE, BUTTON_SECONDARY_STYLE, INPUT_STYLE


class LoginWindow(QWidget):
    login_success = pyqtSignal(object)  # VaultStorage instance

    def __init__(self):
        super().__init__()
        self._mode = 'login'
        self._build()

    # ── UI inşası ─────────────────────────────────────────────

    def _build(self):
        self.setWindowTitle("Syncore")
        self.setFixedSize(460, 580)
        self._center()
        self.setStyleSheet(f"""
            QWidget {{
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 {COLORS['bg_primary']}, stop:1 #0d0814);
                font-family: 'Segoe UI', Arial, sans-serif;
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(50, 50, 50, 40)
        root.setSpacing(0)

        # ── İkon ──────────────────────────────────────────────
        glow_w = QWidget()
        glow_w.setFixedSize(90, 90)
        glow_w.setStyleSheet(f"""
            QWidget {{
                background-color: {COLORS['bg_secondary']};
                border: 2px solid {COLORS['border']};
                border-radius: 22px;
            }}
        """)
        glow = QGraphicsDropShadowEffect()
        glow.setBlurRadius(40)
        glow.setColor(QColor(COLORS['accent']))
        glow.setOffset(0, 0)
        glow_w.setGraphicsEffect(glow)

        icon_lbl = QLabel("🔐", glow_w)
        icon_lbl.setStyleSheet(
            f"color:{COLORS['accent']};font-size:42px;background:transparent;border:none;")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setGeometry(0, 0, 90, 90)

        icon_row = QHBoxLayout()
        icon_row.addStretch()
        icon_row.addWidget(glow_w)
        icon_row.addStretch()
        root.addLayout(icon_row)
        root.addSpacing(24)

        # ── Başlık ────────────────────────────────────────────
        title = QLabel("Syncore")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            f"color:{COLORS['text_primary']};font-size:28px;font-weight:bold;background:transparent;")
        root.addWidget(title)
        root.addSpacing(6)

        # ── Sekme çubuğu ──────────────────────────────────────
        tab_row = QHBoxLayout()
        tab_row.setSpacing(0)

        self._login_tab = self._tab_btn("Giriş Yap")
        self._reg_tab   = self._tab_btn("Kayıt Ol")
        self._login_tab.clicked.connect(lambda: self._switch('login'))
        self._reg_tab.clicked.connect(lambda: self._switch('register'))

        tab_row.addWidget(self._login_tab)
        tab_row.addWidget(self._reg_tab)
        root.addSpacing(20)
        root.addLayout(tab_row)
        root.addSpacing(20)

        # ── Form alanları ─────────────────────────────────────
        self._username_in = self._field("Kullanıcı Adı", icon="👤")
        root.addWidget(self._username_in)
        root.addSpacing(12)

        self._password_in = self._field("Şifre", icon="🔒", password=True)
        root.addWidget(self._password_in)
        root.addSpacing(12)

        self._confirm_w = QWidget()
        confirm_lay = QVBoxLayout(self._confirm_w)
        confirm_lay.setContentsMargins(0, 0, 0, 0)
        self._confirm_in = self._field("Şifre Tekrar", icon="🔒", password=True)
        confirm_lay.addWidget(self._confirm_in)
        root.addWidget(self._confirm_w)
        root.addSpacing(24)

        # ── Ana buton ─────────────────────────────────────────
        self._submit_btn = QPushButton()
        self._submit_btn.setStyleSheet(BUTTON_STYLE)
        self._submit_btn.setMinimumHeight(52)
        self._submit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._submit_btn.clicked.connect(self._on_submit)
        root.addWidget(self._submit_btn)

        root.addSpacing(16)

        # ── Alt bağlantı ──────────────────────────────────────
        self._switch_lbl = QLabel()
        self._switch_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._switch_lbl.setStyleSheet(
            f"color:{COLORS['text_muted']};font-size:12px;background:transparent;")
        self._switch_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        self._switch_lbl.mousePressEvent = lambda _: self._switch(
            'register' if self._mode == 'login' else 'login'
        )
        root.addWidget(self._switch_lbl)

        root.addSpacing(8)

        # ── Hesabı sil butonu ─────────────────────────────────
        self._delete_btn = QPushButton("Hesabı Sil")
        self._delete_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {COLORS['danger']};
                border: none;
                font-size: 11px;
                padding: 4px;
            }}
            QPushButton:hover {{ text-decoration: underline; }}
        """)
        self._delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._delete_btn.clicked.connect(self._on_delete_account)
        root.addWidget(self._delete_btn)

        root.addStretch()

        footer = QLabel("AES-256-GCM  ·  Argon2  ·  HMAC-SHA256")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setStyleSheet(
            f"color:{COLORS['text_muted']};font-size:10px;background:transparent;")
        root.addWidget(footer)

        self._switch('login')

    # ── Yardımcılar ───────────────────────────────────────────

    def _tab_btn(self, text):
        b = QPushButton(text)
        b.setCheckable(True)
        b.setMinimumHeight(38)
        b.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {COLORS['text_muted']};
                border: none;
                border-bottom: 2px solid {COLORS['border']};
                font-size: 14px;
                font-weight: 600;
                padding: 0 20px;
            }}
            QPushButton:checked {{
                color: {COLORS['accent']};
                border-bottom: 2px solid {COLORS['accent']};
            }}
        """)
        return b

    def _field(self, placeholder, icon="", password=False):
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        if icon:
            lbl = QLabel(icon)
            lbl.setFixedSize(42, 46)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(f"""
                QLabel {{
                    background-color: {COLORS['bg_secondary']};
                    color: {COLORS['text_muted']};
                    font-size: 16px;
                    border: 2px solid {COLORS['border']};
                    border-right: none;
                    border-radius: 8px 0 0 8px;
                }}
            """)
            lay.addWidget(lbl)

        inp = QLineEdit()
        inp.setPlaceholderText(placeholder)
        inp.setMinimumHeight(46)
        if password:
            inp.setEchoMode(QLineEdit.EchoMode.Password)
        inp.setStyleSheet(f"""
            QLineEdit {{
                background-color: {COLORS['bg_input']};
                color: {COLORS['text_primary']};
                border: 2px solid {COLORS['border']};
                border-radius: {'0 8px 8px 0' if icon else '8px'};
                padding: 0 14px;
                font-size: 14px;
            }}
            QLineEdit:focus {{
                border-color: {COLORS['accent']};
            }}
        """)
        inp.returnPressed.connect(self._on_submit)
        lay.addWidget(inp)
        row._input = inp
        return row

    def _switch(self, mode):
        self._mode = mode
        is_login = mode == 'login'
        self._login_tab.setChecked(is_login)
        self._reg_tab.setChecked(not is_login)
        self._confirm_w.setVisible(not is_login)
        self._submit_btn.setText("Giriş Yap" if is_login else "Kayıt Ol")
        self._switch_lbl.setText(
            "Hesabın yok mu?  Kayıt Ol" if is_login
            else "Zaten hesabın var mı?  Giriş Yap"
        )
        self._delete_btn.setVisible(is_login)

    def _center(self):
        from PyQt6.QtGui import QScreen
        scr = QScreen.availableGeometry(self.screen())
        self.move((scr.width() - self.width()) // 2, (scr.height() - self.height()) // 2)

    # ── İşlemler ──────────────────────────────────────────────

    def _on_submit(self):
        username = self._username_in._input.text().strip()
        password = self._password_in._input.text()

        if not username:
            QMessageBox.warning(self, "Hata", "Kullanıcı adı boş olamaz.")
            return
        if not password:
            QMessageBox.warning(self, "Hata", "Şifre boş olamaz.")
            return

        if self._mode == 'register':
            self._do_register(username, password)
        else:
            self._do_login(username, password)

    def _on_delete_account(self):
        username = self._username_in._input.text().strip()
        if not username:
            QMessageBox.warning(self, "Hata",
                "Silmek istediğiniz kullanıcı adını girin.")
            return
        reply = QMessageBox.warning(
            self, "Hesabı Sil",
            f"'{username}' kullanıcısının hesabı ve tüm şifreleri kalıcı olarak silinecek.\n\nBu işlem geri alınamaz!",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            db_path = VaultStorage.get_user_db_path(username)
            vault = VaultStorage(db_path)
            if not vault.is_initialized():
                QMessageBox.warning(self, "Hata", "Bu kullanıcı bulunamadı.")
                return
            vault.delete_account()
            # Kullanıcı dizinini tamamen sil
            user_dir = os.path.dirname(db_path)
            shutil.rmtree(user_dir, ignore_errors=True)
            self._username_in._input.clear()
            self._password_in._input.clear()
            QMessageBox.information(
                self, "Silindi", f"'{username}' kullanıcısının tüm verileri silindi.")
        except Exception as e:
            QMessageBox.critical(self, "Hata", str(e))

    def _do_register(self, username, password):
        confirm = self._confirm_in._input.text()
        if len(password) < 8:
            QMessageBox.warning(self, "Hata", "Şifre en az 8 karakter olmalıdır.")
            return
        if password != confirm:
            QMessageBox.warning(self, "Hata", "Şifreler eşleşmiyor.")
            return
        try:
            db_path = VaultStorage.get_user_db_path(username)
            vault = VaultStorage(db_path)
            if vault.is_initialized():
                QMessageBox.warning(
                    self, "Hata",
                    f"'{username}' kullanıcısı zaten mevcut.\nGiriş Yap sekmesini kullanın.")
                self._switch('login')
                return
            vault.initialize_vault(username, password)
            vault.unlock_vault(username, password)
            save_session(username, password)
            self.login_success.emit(vault)
            self.close()
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"Kayıt başarısız: {e}")

    def _do_login(self, username, password):
        try:
            db_path = VaultStorage.get_user_db_path(username)
            vault   = VaultStorage(db_path)

            if not vault.is_initialized():
                # Migration: eski tek-kullanıcı vault.db'yi kontrol et
                old_path = str(Path.home() / ".password_vault" / "vault.db")
                if os.path.exists(old_path):
                    old_vault = VaultStorage(old_path)
                    if old_vault.is_initialized() and \
                       old_vault.unlock_vault(username, password):
                        shutil.copy2(old_path, db_path)
                        vault = VaultStorage(db_path)
                        vault.unlock_vault(username, password)
                        save_session(username, password)
                        self.login_success.emit(vault)
                        self.close()
                        return
                QMessageBox.warning(
                    self, "Hata",
                    f"'{username}' kullanıcısı bulunamadı.\nYeni hesap oluşturmak için Kayıt Ol sekmesini kullanın.")
                return

            if vault.unlock_vault(username, password):
                save_session(username, password)
                self.login_success.emit(vault)
                self.close()
            else:
                QMessageBox.warning(self, "Hata",
                    "Kullanıcı adı veya şifre yanlış.")
                self._password_in._input.clear()
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"Giriş başarısız: {e}")
