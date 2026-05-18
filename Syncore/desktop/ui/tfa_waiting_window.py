"""
2FA Waiting Window - QR Kod ile Kimlik Doğrulama (Phase 3)
===========================================================

Vault şifresi doğrulandıktan sonra gösterilen QR ekranı.
Mobil uygulama QR'ı okur → TCP bağlantısı → Challenge-Response → Vault açılır.
"""

import sys
import os
import io

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QPixmap, QColor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ui.styles import COLORS, BUTTON_SECONDARY_STYLE, BUTTON_STYLE


class TFAWaitingWindow(QWidget):
    """QR tabanlı 2FA bekleme ekranı."""

    approved  = pyqtSignal()
    cancelled = pyqtSignal()
    timeout   = pyqtSignal()

    def __init__(self, server_ip=None, username=None):
        super().__init__()
        self.server_ip       = server_ip
        self.username        = username or ''
        self.timeout_seconds = 300
        self.elapsed_seconds = 0

        self.setWindowTitle('Syncore — QR ile Doğrulama')
        self.setFixedSize(520, 700)
        self._center()
        self._build_ui()
        self._start_timer()

    # ── UI ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 36, 40, 36)
        root.setSpacing(0)

        # ── Title ─────────────────────────────────────────────────────
        title = QLabel('📱  QR ile Giriş Yap')
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"""
            color: {COLORS['text_primary']};
            font-size: 26px;
            font-weight: bold;
            background: transparent;
        """)
        root.addWidget(title)

        root.addSpacing(8)

        sub = QLabel('Mobil uygulamada kamerayı aç ve aşağıdaki QR kodu tara')
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setWordWrap(True)
        sub.setStyleSheet(f'color: {COLORS["text_secondary"]}; font-size: 13px; background: transparent;')
        root.addWidget(sub)

        root.addSpacing(24)

        # ── QR Frame ──────────────────────────────────────────────────
        qr_frame = QFrame()
        qr_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['bg_secondary']};
                border: 2px solid {COLORS['accent']};
                border-radius: 20px;
            }}
        """)
        qr_lay = QVBoxLayout(qr_frame)
        qr_lay.setContentsMargins(24, 24, 24, 24)
        qr_lay.setSpacing(12)

        self._qr_label = QLabel()
        self._qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_label.setFixedHeight(260)
        self._qr_label.setStyleSheet('background: transparent;')
        qr_lay.addWidget(self._qr_label)

        self._status_label = QLabel('📡  Mobil cihaz bekleniyor...')
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setStyleSheet(f'color: {COLORS["accent"]}; font-size: 13px; font-weight: bold; background: transparent;')
        qr_lay.addWidget(self._status_label)

        root.addWidget(qr_frame)

        root.addSpacing(20)

        # ── IP / Secret info ──────────────────────────────────────────
        info_frame = QFrame()
        info_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {COLORS['bg_secondary']};
                border: 1px solid {COLORS['border']};
                border-radius: 12px;
            }}
        """)
        info_lay = QVBoxLayout(info_frame)
        info_lay.setContentsMargins(16, 12, 16, 12)
        info_lay.setSpacing(6)

        hint = QLabel('QR taranamıyorsa mobil uygulamada manuel giriş yapın:')
        hint.setStyleSheet(f'color: {COLORS["text_muted"]}; font-size: 11px; background: transparent;')
        info_lay.addWidget(hint)

        ip_text = f'{self.server_ip}:8765' if self.server_ip else '—'

        for label, value in [('Server IP', ip_text)]:
            row = QHBoxLayout()
            lbl = QLabel(f'{label}:')
            lbl.setStyleSheet(f'color: {COLORS["text_secondary"]}; font-size: 11px; background: transparent; min-width: 160px;')
            val = QLabel(value)
            val.setStyleSheet(f'color: {COLORS["text_primary"]}; font-size: 11px; font-family: monospace; background: transparent;')
            row.addWidget(lbl)
            row.addWidget(val)
            row.addStretch()
            info_lay.addLayout(row)

        root.addWidget(info_frame)

        root.addSpacing(20)

        # ── Cancel button ─────────────────────────────────────────────
        cancel_btn = QPushButton('İptal')
        cancel_btn.setStyleSheet(BUTTON_SECONDARY_STYLE)
        cancel_btn.setMinimumHeight(48)
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self._on_cancel)
        root.addWidget(cancel_btn)

        logout_btn = QPushButton('Oturumu Kapat')
        logout_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none;
                color: #6b7280; font-size: 11px;
            }}
            QPushButton:hover {{ color: #ef4444; }}
        """)
        logout_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        logout_btn.clicked.connect(self._on_logout)
        root.addWidget(logout_btn)

        self.setStyleSheet(f'QWidget {{ background-color: {COLORS["bg_primary"]}; }}')

        # Generate QR code
        self._generate_qr()

    def _generate_qr(self):
        """QR kodu oluştur ve göster."""
        if not self.server_ip:
            self._qr_label.setText('⚠️ Server bilgisi eksik')
            self._qr_label.setStyleSheet(f'color: {COLORS["warning"]}; background: transparent;')
            return

        try:
            import qrcode
            data = f'pvault://{self.server_ip}:8765?user={self.username}'
            qr = qrcode.QRCode(box_size=7, border=2)
            qr.add_data(data)
            qr.make(fit=True)

            # Dark themed QR
            img = qr.make_image(fill_color='white', back_color='#171717')
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            buf.seek(0)

            pix = QPixmap()
            pix.loadFromData(buf.read())
            self._qr_label.setPixmap(
                pix.scaled(240, 240,
                           Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
            )
        except ImportError:
            self._qr_label.setText('qrcode paketi eksik\npip install qrcode[pil]')
            self._qr_label.setStyleSheet(f'color: {COLORS["warning"]}; font-size: 12px; background: transparent;')
        except Exception as ex:
            self._qr_label.setText(f'QR hatası: {ex}')

    # ── Timer ────────────────────────────────────────────────────────

    def _start_timer(self):
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)

    def _tick(self):
        self.elapsed_seconds += 1
        remaining = self.timeout_seconds - self.elapsed_seconds
        if remaining > 0:
            self._status_label.setText(f'📡  Mobil cihaz bekleniyor... ({remaining}s)')
        else:
            self._timer.stop()
            self._on_timeout()

    # ── Public slots (called from main thread via QTimer) ─────────────

    def on_approve(self):
        """Mobil onayladığında çağrılır (thread-safe: always call via QTimer.singleShot)."""
        self._timer.stop()
        self._status_label.setText('✅  Doğrulama başarılı!')
        self._status_label.setStyleSheet(f'color: {COLORS["success"]}; font-size: 14px; font-weight: bold; background: transparent;')
        QTimer.singleShot(600, lambda: self.approved.emit())

    def _on_cancel(self):
        self._timer.stop()
        self.cancelled.emit()
        self.close()

    def _on_logout(self):
        self._timer.stop()
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from session_manager import clear_session
        clear_session()
        self.cancelled.emit()
        self.close()

    def _on_timeout(self):
        self._status_label.setText('⏱  Zaman aşımı! Tekrar deneyin.')
        self._status_label.setStyleSheet(f'color: {COLORS["danger"]}; font-size: 13px; font-weight: bold; background: transparent;')
        QTimer.singleShot(2000, lambda: self.timeout.emit())

    # ── Helpers ──────────────────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        try:
            import ctypes
            hwnd = int(self.winId())
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 20, ctypes.byref(ctypes.c_int(1)), ctypes.sizeof(ctypes.c_int))
        except Exception:
            pass

    def _center(self):
        from PyQt6.QtGui import QScreen
        scr = QScreen.availableGeometry(self.screen())
        self.move((scr.width() - self.width()) // 2, (scr.height() - self.height()) // 2)
