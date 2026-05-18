"""
Manager Window - Phase 3
========================
Card-based list, filter chips, password strength, QR pairing.
"""

import sys
import os
import re
import base64
import secrets

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QFrame, QMessageBox, QDialog, QDialogButtonBox,
    QTextEdit, QApplication, QProgressBar, QSizePolicy, QTabWidget,
    QButtonGroup, QStyle, QGraphicsOpacityEffect
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPropertyAnimation, QEasingCurve, QSize
from PyQt6.QtGui import QFont, QPixmap, QColor, QPainter, QBrush, QIcon

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui.styles import (
    COLORS, BUTTON_STYLE, BUTTON_SECONDARY_STYLE, BUTTON_DANGER_STYLE,
    INPUT_STYLE, LABEL_TITLE_STYLE, LABEL_SUBTITLE_STYLE,
    CHIP_BUTTON_STYLE, CARD_STYLE, SCROLL_AREA_STYLE,
    STRENGTH_WEAK_STYLE, STRENGTH_MEDIUM_STYLE, STRENGTH_STRONG_STYLE,
    SEARCH_BAR_STYLE
)
from network_server import NetworkServer


def _si(sp: QStyle.StandardPixmap, size: int = 22) -> QIcon:
    """Standard icon'u dark tema için beyaza boyayarak döndürür."""
    raw = QApplication.style().standardIcon(sp)
    pm  = raw.pixmap(size, size)
    out = QPixmap(pm.size())
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    p.drawPixmap(0, 0, pm)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(out.rect(), QColor('#ffffff'))
    p.end()
    return QIcon(out)


SP = QStyle.StandardPixmap


# ── Dark title bar (Windows DWM) ───────────────────────────────────────────

def _dark_titlebar(widget):
    """Windows 10/11'de başlık çubuğunu koyu yapar."""
    try:
        import ctypes
        hwnd = int(widget.winId())
        for attr in (20, 19):  # Build 19041+ önce, eski build fallback
            try:
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(ctypes.c_int(1)), ctypes.sizeof(ctypes.c_int))
                break
            except Exception:
                pass
    except Exception:
        pass


# ── Custom Confirm Dialog ───────────────────────────────────────────────────

class ConfirmDialog(QDialog):
    """Temamıza uyan onay dialogu — Evet / Hayır."""

    def __init__(self, title: str, message: str, parent=None, danger=True):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setFixedWidth(420)
        self.setStyleSheet(f'QDialog {{ background-color: {COLORS["bg_primary"]}; }}')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 32, 24)
        lay.setSpacing(20)

        msg_lbl = QLabel(message)
        msg_lbl.setWordWrap(True)
        msg_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg_lbl.setStyleSheet(
            f'color: {COLORS["text_primary"]}; font-size: 14px; background: transparent;')
        lay.addWidget(msg_lbl)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        hayir_btn = QPushButton('Hayır')
        hayir_btn.setStyleSheet(BUTTON_SECONDARY_STYLE)
        hayir_btn.setMinimumHeight(40)
        hayir_btn.setMinimumWidth(100)
        hayir_btn.clicked.connect(self.reject)

        evet_btn = QPushButton('Evet')
        evet_btn.setStyleSheet(BUTTON_DANGER_STYLE if danger else BUTTON_STYLE)
        evet_btn.setMinimumHeight(40)
        evet_btn.setMinimumWidth(100)
        evet_btn.clicked.connect(self.accept)

        btn_row.addStretch()
        btn_row.addWidget(hayir_btn)
        btn_row.addWidget(evet_btn)
        lay.addLayout(btn_row)

    def showEvent(self, event):
        super().showEvent(event)
        _dark_titlebar(self)


def _confirm(parent, title: str, message: str, danger=True) -> bool:
    return ConfirmDialog(title, message, parent, danger).exec() == QDialog.DialogCode.Accepted


# ── Helpers ────────────────────────────────────────────────────────────────

def _vault_title(name: str) -> str:
    """'Fiko' → "Fiko'nun Kasası" şeklinde Türkçe iyelik eki ekler."""
    if not name:
        return 'Kasam'
    all_vowels = set('aeıioöuüAEIİOÖUÜ')
    last_vowel = next((c.lower() for c in reversed(name) if c in all_vowels), '')
    ends_vowel = name[-1] in all_vowels
    if last_vowel in 'aı':
        suffix = "'nın" if ends_vowel else "'ın"
    elif last_vowel in 'eiİ':
        suffix = "'nin" if ends_vowel else "'in"
    elif last_vowel in 'ou':
        suffix = "'nun" if ends_vowel else "'un"
    elif last_vowel in 'öü':
        suffix = "'nün" if ends_vowel else "'ün"
    else:
        suffix = "'nin"
    return f"{name}{suffix} Kasası"


def get_site_emoji(title: str) -> str:
    """Return a relevant emoji based on title keywords (TR + EN)."""
    t = title.lower()
    mapping = [
        # E-posta / Mail
        (['gmail', 'mail', 'email', 'e-posta', 'eposta', 'outlook', 'hotmail',
          'yahoo', 'yandex', 'proton', 'imap', 'smtp'], '📧'),
        # Bankacılık / Finans
        (['bank', 'banka', 'finans', 'finance', 'kredi', 'credit', 'para',
          'money', 'dolar', 'dollar', 'euro', 'borsa', 'invest', 'wallet',
          'cüzdan', 'iban', 'swift', 'akbank', 'garanti', 'yapıkredi',
          'ziraat', 'halkbank', 'isbank', 'iş bank', 'vakıf'], '🏦'),
        # Kripto
        (['bitcoin', 'btc', 'ethereum', 'eth', 'binance', 'kripto', 'crypto',
          'coinbase', 'bybit', 'okx', 'kucoin', 'metamask', 'web3'], '🪙'),
        # Oyun / Gaming
        (['oyun', 'game', 'steam', 'epic', 'xbox', 'playstation', 'ps4',
          'ps5', 'nintendo', 'gog', 'ubisoft', 'ea ', 'origin', 'battle',
          'riot', 'league', 'minecraft', 'roblox', 'twitch'], '🎮'),
        # Sosyal Medya
        (['instagram', 'tiktok', 'snapchat', 'pinterest', 'tumblr'], '📸'),
        (['twitter', ' x ', 'tweet'], '🐦'),
        (['facebook', 'fb', 'meta', 'messenger'], '📘'),
        (['linkedin'], '💼'),
        (['reddit'], '🤖'),
        # Mesajlaşma
        (['whatsapp', 'telegram', 'signal', 'viber', 'discord', 'slack',
          'teams', 'skype', 'mesaj'], '💬'),
        # Video / Yayın
        (['netflix', 'youtube', 'hulu', 'disney', 'prime video', 'mubi',
          'blutv', 'gain ', 'exxen', 'tod ', 'twitch', 'vimeo'], '🎬'),
        # Müzik
        (['spotify', 'apple music', 'soundcloud', 'deezer', 'tidal',
          'müzik', 'music'], '🎵'),
        # Alışveriş
        (['amazon', 'trendyol', 'hepsiburada', 'n11', 'gittigidiyor',
          'shopify', 'etsy', 'ebay', 'aliexpress', 'alışveriş', 'shop'], '🛒'),
        # Bulut / Depolama
        (['drive', 'dropbox', 'icloud', 'onedrive', 'mega ', 'box ',
          'bulut', 'cloud', 'storage'], '☁️'),
        # Geliştirici / Kod
        (['github', 'gitlab', 'bitbucket', 'git ', 'npm', 'docker',
          'heroku', 'vercel', 'netlify', 'aws', 'azure', 'gcp'], '💻'),
        # Google
        (['google'], '🌐'),
        # Apple
        (['apple', 'icloud', 'itunes', 'appstore'], '🍎'),
        # Microsoft / Windows
        (['microsoft', 'windows', 'office', 'azure'], '🪟'),
        # Güvenlik / VPN
        (['vpn', 'ssh', '2fa', 'güvenlik', 'security', 'firewall',
          'nordvpn', 'expressvpn', 'proton'], '🔒'),
        # Sunucu / Sistem
        (['server', 'sunucu', 'hosting', 'cpanel', 'plesk', 'nginx',
          'apache', 'ftp', 'rdp', 'linux'], '🖥️'),
        # Eğitim
        (['school', 'okul', 'üniversite', 'university', 'eğitim',
          'udemy', 'coursera', 'duolingo', 'meb', 'öğrenci'], '🎓'),
        # Sağlık
        (['sağlık', 'health', 'hospital', 'hastane', 'doktor', 'doctor',
          'medikal', 'medical', 'sigorta', 'insurance'], '🏥'),
        # Seyahat
        (['seyahat', 'travel', 'uçak', 'airline', 'hotel', 'otel',
          'airbnb', 'booking', 'thy', 'pegasus'], '✈️'),
        # Yemek / Teslimat
        (['yemek', 'food', 'yemeksepeti', 'getir', 'trendyol yemek',
          'restaurant', 'pizza', 'burger'], '🍔'),
        # E-devlet / Resmi
        (['devlet', 'government', 'e-devlet', 'egov', 'kimlik', 'pasaport',
          'vergi', 'sgk', 'belediye'], '🏛️'),
        # Ödeme / Kart
        (['paypal', 'stripe', 'ödeme', 'payment', 'papara', 'ininal',
          'card', 'kart', 'visa', 'mastercard'], '💳'),
        # Video konferans
        (['zoom', 'meet', 'webex', 'teams', 'toplantı', 'conference'], '📹'),
        # Telefon / Mobil
        (['telefon', 'phone', 'mobile', 'sim', 'turkcell', 'vodafone',
          'türk telekom', 'operatör'], '📱'),
        # Not / Üretkenlik
        (['notion', 'obsidian', 'evernote', 'trello', 'jira', 'asana',
          'todoist', 'not ', 'note'], '📝'),
    ]
    for keywords, emoji in mapping:
        if any(kw in t for kw in keywords):
            return emoji
    return '🔑'


# ── Kategori sistemi ────────────────────────────────────────────────────────

CATEGORY_MAP = [
    (['getir', 'yemeksepeti', 'uber eat', 'ubereats', 'dominos', 'pizza',
      'burger', 'yemek', 'food', 'trendyol yemek', 'migros', 'a101', 'bim ',
      'carrefour', 'market'], 'Yemek & Market', '🍔'),
    (['akbank', 'garanti', 'yapıkredi', 'ziraat', 'halkbank', 'isbank',
      'iş bank', 'vakıf', 'banka', 'bank', 'finans', 'finance', 'iban',
      'swift', 'borsa', 'invest', 'kredi', 'credit', 'para ', 'dolar',
      'euro ', 'papara', 'ininal'], 'Banka & Finans', '🏦'),
    (['bitcoin', 'btc', 'ethereum', 'eth', 'binance', 'kripto', 'crypto',
      'coinbase', 'bybit', 'okx', 'kucoin', 'metamask'], 'Kripto', '🪙'),
    (['steam', 'epic', 'xbox', 'playstation', 'ps4', 'ps5', 'nintendo',
      'riot', 'league', 'minecraft', 'roblox', 'oyun', 'game', 'gog',
      'ubisoft', 'battle.net', 'origin', 'ea '], 'Oyun', '🎮'),
    (['whatsapp', 'telegram', 'signal', 'discord', 'slack', 'viber',
      'messenger', 'mesaj', 'skype'], 'Mesajlaşma', '💬'),
    (['instagram', 'tiktok', 'twitter', 'facebook', 'reddit', 'snapchat',
      'linkedin', 'pinterest', 'tumblr', 'sosyal'], 'Sosyal Medya', '📱'),
    (['netflix', 'youtube', 'hulu', 'disney', 'mubi', 'blutv', 'exxen',
      'twitch', 'vimeo', 'gain ', 'tod ', 'eğlence'], 'Eğlence', '🎬'),
    (['spotify', 'soundcloud', 'deezer', 'tidal', 'müzik', 'music',
      'apple music'], 'Müzik', '🎵'),
    (['gmail', 'mail', 'email', 'e-posta', 'eposta', 'outlook', 'hotmail',
      'yahoo', 'yandex', 'proton', 'imap', 'smtp'], 'E-posta', '📧'),
    (['amazon', 'trendyol', 'hepsiburada', 'n11', 'gittigidiyor', 'etsy',
      'ebay', 'aliexpress', 'alışveriş', 'shopify'], 'Alışveriş', '🛒'),
    (['github', 'gitlab', 'bitbucket', 'docker', 'heroku', 'vercel',
      'netlify', 'aws', 'azure', 'gcp', 'npm ', 'linux', 'cpanel',
      'plesk', 'hosting', 'server', 'sunucu', 'ftp', 'rdp', 'ssh'],
     'Geliştirici', '💻'),
    (['vpn', '2fa', 'güvenlik', 'security', 'firewall', 'nordvpn',
      'expressvpn', 'protonvpn'], 'Güvenlik', '🔒'),
    (['booking', 'airbnb', 'thy', 'pegasus', 'hotel', 'otel', 'seyahat',
      'travel', 'airline', 'uçak'], 'Seyahat', '✈️'),
    (['e-devlet', 'devlet', 'sgk', 'belediye', 'vergi', 'government',
      'kimlik', 'pasaport', 'meb'], 'Resmi', '🏛️'),
    (['google', 'apple', 'microsoft', 'icloud', 'drive', 'dropbox',
      'onedrive', 'mega ', 'cloud', 'bulut', 'windows', 'office',
      'itunes', 'appstore'], 'Bulut & Hesap', '☁️'),
    (['okul', 'üniversite', 'university', 'udemy', 'coursera', 'duolingo',
      'eğitim', 'moodle', 'öğrenci'], 'Eğitim', '🎓'),
    (['sağlık', 'health', 'hospital', 'hastane', 'sigorta', 'doktor',
      'medikal'], 'Sağlık', '🏥'),
    (['turkcell', 'vodafone', 'türk telekom', 'telefon', 'gsm',
      'operatör'], 'Telekom', '📡'),
]


def get_category(title: str):
    """Başlığa göre (name, emoji) döner. Eşleşme yoksa None."""
    t = title.lower()
    for keywords, name, emoji in CATEGORY_MAP:
        if any(kw in t for kw in keywords):
            return (name, emoji)
    return None


def score_password(pwd: str) -> tuple[int, str, str]:
    """Return (score 0-100, label, style_key: weak/medium/strong)."""
    if not pwd:
        return 0, '', 'weak'
    score = 0
    if len(pwd) >= 8:  score += 20
    if len(pwd) >= 12: score += 15
    if len(pwd) >= 16: score += 15
    if re.search(r'[A-Z]', pwd): score += 15
    if re.search(r'[a-z]', pwd): score += 10
    if re.search(r'\d', pwd):    score += 10
    if re.search(r'[^A-Za-z0-9]', pwd): score += 15
    score = min(score, 100)
    if score < 40:
        return score, f'Zayıf ({score}/100)', 'weak'
    elif score < 70:
        return score, f'Orta ({score}/100)', 'medium'
    else:
        return score, f'Güçlü ({score}/100)', 'strong'


# ── AddPasswordDialog with strength meter ──────────────────────────────────

class AddPasswordDialog(QDialog):
    def __init__(self, parent=None, edit_mode=False, entry_data=None):
        super().__init__(parent)
        self.edit_mode = edit_mode
        self.entry_data = entry_data or {}
        self.setWindowTitle('Şifreyi Düzenle' if edit_mode else 'Yeni Şifre Ekle')
        self.setModal(True)
        self.setFixedWidth(520)
        self._build()

    def showEvent(self, event):
        super().showEvent(event)
        _dark_titlebar(self)

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(14)
        lay.setContentsMargins(32, 32, 32, 32)

        title = QLabel('Düzenle' if self.edit_mode else 'Yeni Şifre')
        title.setStyleSheet(LABEL_TITLE_STYLE)
        lay.addWidget(title)

        self.title_in = self._input('Başlık  (ör: Gmail, Netflix)', 'title')
        self.user_in  = self._input('Kullanıcı Adı / E-posta', 'username')

        # Password row
        pwd_row = QHBoxLayout()
        self.pwd_in = QLineEdit()
        self.pwd_in.setPlaceholderText('Şifre')
        self.pwd_in.setStyleSheet(INPUT_STYLE)
        if self.edit_mode:
            self.pwd_in.setText(self.entry_data.get('password', ''))
        self.pwd_in.textChanged.connect(self._update_strength)

        gen_btn = QPushButton()
        gen_btn.setIcon(_si(SP.SP_CommandLink, 20))
        gen_btn.setIconSize(QSize(20, 20))
        gen_btn.setToolTip('Güçlü şifre üret')
        gen_btn.setFixedSize(40, 40)
        gen_btn.setStyleSheet(BUTTON_STYLE)
        gen_btn.clicked.connect(self._generate_password)
        pwd_row.addWidget(self.pwd_in)
        pwd_row.addWidget(gen_btn)
        lay.addLayout(pwd_row)

        # Strength bar
        self.strength_bar = QProgressBar()
        self.strength_bar.setRange(0, 100)
        self.strength_bar.setValue(0)
        self.strength_bar.setTextVisible(False)
        self.strength_bar.setFixedHeight(6)
        self.strength_bar.setStyleSheet(STRENGTH_WEAK_STYLE)
        lay.addWidget(self.strength_bar)

        self.strength_lbl = QLabel('')
        self.strength_lbl.setStyleSheet(f'color: {COLORS["text_muted"]}; font-size: 11px; background: transparent;')
        lay.addWidget(self.strength_lbl)

        self.url_in   = self._input('URL  (opsiyonel)', 'url')
        self.notes_in = QTextEdit()
        self.notes_in.setPlaceholderText('Notlar  (opsiyonel)')
        self.notes_in.setStyleSheet(INPUT_STYLE)
        self.notes_in.setFixedHeight(80)
        if self.edit_mode:
            self.notes_in.setPlainText(self.entry_data.get('notes', ''))
        lay.addWidget(self.notes_in)

        # Update strength if editing
        if self.edit_mode:
            self._update_strength(self.pwd_in.text())

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btn_box.accepted.connect(self._validate)
        btn_box.rejected.connect(self.reject)
        for b in btn_box.buttons():
            std = btn_box.standardButton(b)
            if std == QDialogButtonBox.StandardButton.Ok:
                b.setStyleSheet(BUTTON_STYLE); b.setText('Kaydet')
            else:
                b.setStyleSheet(BUTTON_SECONDARY_STYLE); b.setText('İptal')
            b.setMinimumWidth(100)
        lay.addWidget(btn_box)

        self.setStyleSheet(f'QDialog {{ background-color: {COLORS["bg_primary"]}; }}')

    def _input(self, placeholder, field):
        w = QLineEdit()
        w.setPlaceholderText(placeholder)
        w.setStyleSheet(INPUT_STYLE)
        if self.edit_mode:
            w.setText(self.entry_data.get(field, ''))
        self.layout().addWidget(w)
        return w

    def _update_strength(self, text):
        score, label, key = score_password(text)
        self.strength_bar.setValue(score)
        styles = {'weak': STRENGTH_WEAK_STYLE, 'medium': STRENGTH_MEDIUM_STYLE, 'strong': STRENGTH_STRONG_STYLE}
        colors = {'weak': COLORS['danger'], 'medium': COLORS['warning'], 'strong': COLORS['success']}
        self.strength_bar.setStyleSheet(styles[key])
        self.strength_lbl.setStyleSheet(f'color: {colors[key]}; font-size: 11px; background: transparent;')
        self.strength_lbl.setText(label)

    def _generate_password(self):
        import string
        chars = string.ascii_letters + string.digits + '!@#$%^&*'
        pwd = ''.join(secrets.choice(chars) for _ in range(20))
        self.pwd_in.setText(pwd)
        clipboard = QApplication.clipboard()
        clipboard.setText(pwd)

    def _validate(self):
        if not self.title_in.text().strip():
            QMessageBox.warning(self, 'Hata', 'Başlık gereklidir!'); return
        if not self.user_in.text().strip():
            QMessageBox.warning(self, 'Hata', 'Kullanıcı adı gereklidir!'); return
        if not self.pwd_in.text().strip():
            QMessageBox.warning(self, 'Hata', 'Şifre gereklidir!'); return
        self.accept()

    def get_data(self):
        return {
            'title':    self.title_in.text().strip(),
            'username': self.user_in.text().strip(),
            'password': self.pwd_in.text().strip(),
            'url':      self.url_in.text().strip(),
            'notes':    self.notes_in.toPlainText().strip(),
        }


# ── Password Card Widget ───────────────────────────────────────────────────

class PasswordCard(QFrame):
    """Single password entry displayed as a card."""
    sig_view     = pyqtSignal(int)   # kart gövdesine tıklanınca
    sig_copy     = pyqtSignal(int)
    sig_edit     = pyqtSignal(int)
    sig_delete   = pyqtSignal(int)
    sig_favorite = pyqtSignal(int)
    sig_trash    = pyqtSignal(int)
    sig_restore  = pyqtSignal(int)

    def __init__(self, entry: dict, in_trash=False, parent=None):
        super().__init__(parent)
        self.entry_id = entry['id']
        self.in_trash = in_trash
        self._action_btns = []
        self._normal_style = f"""
            QFrame {{
                background-color: {COLORS['bg_surface']};
                border: 1px solid rgba(255, 255, 255, 0.05);
                border-radius: 16px;
            }}"""
        self._hover_style = f"""
            QFrame {{
                background-color: {COLORS['bg_tertiary']};
                border: 1px solid {COLORS['accent']};
                border-radius: 16px;
            }}"""
        self.setStyleSheet(self._normal_style)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._build(entry)
        self._set_btns_dim(True)

    def _build(self, e):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(14)

        # Emoji avatar
        avatar = QLabel(get_site_emoji(e['title']))
        avatar.setFixedSize(48, 48)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setStyleSheet(f"""
            QLabel {{
                background-color: {COLORS['bg_tertiary']};
                border-radius: 12px;
                font-size: 24px;
                border: 1px solid {COLORS['border']};
            }}""")
        lay.addWidget(avatar)

        # Text block
        txt = QVBoxLayout()
        txt.setSpacing(3)

        title_row = QHBoxLayout()
        title_lbl = QLabel(e['title'])
        title_lbl.setStyleSheet(f'font-size: 15px; font-weight: bold; color: {COLORS["text_primary"]}; background: transparent;')
        title_row.addWidget(title_lbl)
        if e.get('is_favorite'):
            fav_lbl = QLabel('⭐')
            fav_lbl.setStyleSheet('background: transparent; font-size: 14px;')
            title_row.addWidget(fav_lbl)
        title_row.addStretch()
        txt.addLayout(title_row)

        user_lbl = QLabel(e['username'])
        user_lbl.setStyleSheet(f'font-size: 12px; color: {COLORS["text_secondary"]}; background: transparent;')
        txt.addWidget(user_lbl)

        # Kategori rozeti
        cat = e.get('_category')
        if cat:
            cat_lbl = QLabel(f'{cat[1]} {cat[0]}')
            cat_lbl.setStyleSheet(f"""
                QLabel {{
                    background-color: rgba(122,43,191,0.12);
                    color: {COLORS['accent_light']};
                    border: 1px solid rgba(122,43,191,0.25);
                    border-radius: 4px;
                    font-size: 10px;
                    padding: 0px 5px;
                }}""")
            txt.addWidget(cat_lbl)

        # Strength indicator
        pwd_score, pwd_lbl, pwd_key = score_password(e.get('_password_preview', ''))
        if e.get('_password_preview'):
            if pwd_key == 'weak':
                warn = QLabel('⚠ Zayıf Şifre')
                warn.setStyleSheet(f"""
                    QLabel {{
                        background-color: rgba(239,68,68,0.15);
                        color: {COLORS['danger']};
                        border: 1px solid rgba(239,68,68,0.4);
                        border-radius: 5px;
                        font-size: 11px;
                        font-weight: 600;
                        padding: 1px 6px;
                    }}""")
                txt.addWidget(warn)
            else:
                colors_map = {'medium': COLORS['warning'], 'strong': COLORS['success']}
                pill = QLabel(pwd_lbl)
                pill.setStyleSheet(f'font-size: 10px; color: {colors_map[pwd_key]}; background: transparent;')
                txt.addWidget(pill)

        lay.addLayout(txt)
        lay.addStretch()

        # Action buttons
        if self.in_trash:
            restore_btn = self._btn('Geri Al', 'Çöp kutusundan geri al', restore=True)
            restore_btn.clicked.connect(lambda: self.sig_restore.emit(self.entry_id))
            lay.addWidget(restore_btn)

            del_btn = self._btn('Kalıcı Sil', 'Kalıcı olarak sil', always_danger=True)
            del_btn.clicked.connect(lambda: self.sig_delete.emit(self.entry_id))
            lay.addWidget(del_btn)
        else:
            fav_label = 'Favoriden Çıkar' if e.get('is_favorite') else 'Favori'
            fav_btn = self._btn(fav_label, fav_label, star=True)
            fav_btn.clicked.connect(lambda: self.sig_favorite.emit(self.entry_id))
            lay.addWidget(fav_btn)

            copy_btn = self._btn('Kopyala', 'Şifreyi kopyala')
            copy_btn.clicked.connect(lambda: self.sig_copy.emit(self.entry_id))
            lay.addWidget(copy_btn)

            edit_btn = self._btn('Düzenle', 'Düzenle')
            edit_btn.clicked.connect(lambda: self.sig_edit.emit(self.entry_id))
            lay.addWidget(edit_btn)

            trash_btn = self._btn('Sil', 'Çöp kutusuna taşı', danger=True)
            trash_btn.clicked.connect(lambda: self.sig_trash.emit(self.entry_id))
            lay.addWidget(trash_btn)

    def _btn(self, label, tip, danger=False, star=False, always_danger=False, restore=False):
        b = QPushButton(label)
        b.setToolTip(tip)
        b.setFixedHeight(30)
        b.setContentsMargins(0, 0, 0, 0)
        if restore:
            b.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLORS['bg_tertiary']};
                    border: 1px solid {COLORS['border']};
                    border-radius: 6px;
                    padding: 0 10px;
                    font-size: 11px;
                    font-weight: 600;
                    color: {COLORS['text_muted']};
                }}
                QPushButton:hover {{
                    background-color: rgba(16,185,129,0.15);
                    border-color: rgba(16,185,129,0.5);
                    color: {COLORS['success']};
                }}""")
        elif always_danger:
            b.setStyleSheet(f"""
                QPushButton {{
                    background-color: rgba(239,68,68,0.15);
                    border: 1px solid rgba(239,68,68,0.35);
                    border-radius: 6px;
                    padding: 0 10px;
                    font-size: 11px;
                    font-weight: 600;
                    color: {COLORS['danger']};
                }}
                QPushButton:hover {{
                    background-color: {COLORS['danger']};
                    border-color: {COLORS['danger']};
                    color: #ffffff;
                }}""")
        elif danger:
            b.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLORS['bg_tertiary']};
                    border: 1px solid {COLORS['border']};
                    border-radius: 6px;
                    padding: 0 10px;
                    font-size: 11px;
                    font-weight: 600;
                    color: {COLORS['text_muted']};
                }}
                QPushButton:hover {{
                    background-color: rgba(239,68,68,0.15);
                    border-color: rgba(239,68,68,0.5);
                    color: {COLORS['danger']};
                }}""")
        elif star:
            b.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLORS['bg_tertiary']};
                    border: 1px solid {COLORS['border']};
                    border-radius: 6px;
                    padding: 0 10px;
                    font-size: 11px;
                    font-weight: 600;
                    color: {'#f59e0b' if label == 'Favoriden Çıkar' else COLORS['text_muted']};
                }}
                QPushButton:hover {{
                    background-color: rgba(245,158,11,0.15);
                    border-color: rgba(245,158,11,0.5);
                    color: #f59e0b;
                }}""")
        else:
            b.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLORS['bg_tertiary']};
                    border: 1px solid {COLORS['border']};
                    border-radius: 6px;
                    padding: 0 10px;
                    font-size: 11px;
                    font-weight: 600;
                    color: {COLORS['text_secondary']};
                }}
                QPushButton:hover {{
                    background-color: rgba(122,43,191,0.2);
                    border-color: {COLORS['accent']};
                    color: {COLORS['accent_light']};
                }}""")
        eff = QGraphicsOpacityEffect(b)
        eff.setOpacity(0.45)
        b.setGraphicsEffect(eff)
        self._action_btns.append(b)
        return b

    def _set_btns_dim(self, dim: bool):
        for btn in self._action_btns:
            eff = btn.graphicsEffect()
            if isinstance(eff, QGraphicsOpacityEffect):
                eff.setOpacity(0.45 if dim else 1.0)

    def mousePressEvent(self, e):
        """Kart gövdesine tıklanınca görüntüleme sinyali gönder.
        QPushButton çocukları kendi event'larını consume eder, buraya ulaşmaz."""
        self.sig_view.emit(self.entry_id)
        super().mousePressEvent(e)

    def enterEvent(self, e):
        self.setStyleSheet(self._hover_style)
        self._set_btns_dim(False)

    def leaveEvent(self, e):
        self.setStyleSheet(self._normal_style)
        self._set_btns_dim(True)


# ── ViewPasswordDialog ─────────────────────────────────────────────────────

class ViewPasswordDialog(QDialog):
    """Şifre detaylarını salt-okunur gösterir."""

    def __init__(self, entry: dict, password: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'🔑  {entry["title"]}')
        self.setModal(True)
        self.setFixedWidth(500)
        self.setStyleSheet(f'QDialog {{ background-color: {COLORS["bg_primary"]}; }}')
        self._build(entry, password)

    def showEvent(self, event):
        super().showEvent(event)
        _dark_titlebar(self)

    def _build(self, e, pwd):
        lay = QVBoxLayout(self)
        lay.setSpacing(16)
        lay.setContentsMargins(32, 32, 32, 32)

        # Başlık satırı
        hdr = QHBoxLayout()
        icon = QLabel(get_site_emoji(e['title']))
        icon.setFixedSize(52, 52)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(f"""QLabel {{
            background-color: {COLORS['bg_secondary']};
            border-radius: 14px; font-size: 26px;
            border: 1px solid {COLORS['border']};}}""")
        hdr.addWidget(icon)
        hdr.addSpacing(12)
        ttl = QLabel(e['title'])
        ttl.setStyleSheet(f'font-size: 20px; font-weight: bold; color: {COLORS["text_primary"]}; background: transparent;')
        hdr.addWidget(ttl)
        hdr.addStretch()
        lay.addLayout(hdr)

        # Kullanıcı adı
        self._add_field(lay, 'Kullanıcı Adı', e.get('username', ''), copyable=True)

        # Şifre (gizli/göster toggle)
        pwd_row = QVBoxLayout()
        pwd_lbl = QLabel('Şifre')
        pwd_lbl.setStyleSheet(f'color: {COLORS["text_muted"]}; font-size: 11px; background: transparent;')
        pwd_row.addWidget(pwd_lbl)

        pwd_hbox = QHBoxLayout()
        self._pwd_field = QLineEdit(pwd)
        self._pwd_field.setReadOnly(True)
        self._pwd_field.setEchoMode(QLineEdit.EchoMode.Password)
        self._pwd_field.setStyleSheet(INPUT_STYLE)
        pwd_hbox.addWidget(self._pwd_field)

        eye_btn = QPushButton()
        eye_btn.setIcon(_si(SP.SP_FileDialogInfoView, 20))
        eye_btn.setIconSize(QSize(20, 20))
        eye_btn.setFixedSize(40, 40)
        eye_btn.setCheckable(True)
        eye_btn.setToolTip('Göster / Gizle')
        eye_btn.setStyleSheet(BUTTON_SECONDARY_STYLE)
        eye_btn.toggled.connect(lambda checked: self._pwd_field.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password))
        pwd_hbox.addWidget(eye_btn)

        copy_pwd_btn = QPushButton()
        copy_pwd_btn.setIcon(_si(SP.SP_FileIcon, 20))
        copy_pwd_btn.setIconSize(QSize(20, 20))
        copy_pwd_btn.setFixedSize(40, 40)
        copy_pwd_btn.setToolTip('Şifreyi Kopyala')
        copy_pwd_btn.setStyleSheet(BUTTON_SECONDARY_STYLE)
        copy_pwd_btn.clicked.connect(lambda: (
            QApplication.clipboard().setText(pwd),
            self._flash(copy_pwd_btn, '✅')
        ))
        pwd_hbox.addWidget(copy_pwd_btn)
        pwd_row.addLayout(pwd_hbox)

        # Güç göstergesi
        score, label, key = score_password(pwd)
        colors_map = {'weak': COLORS['danger'], 'medium': COLORS['warning'], 'strong': COLORS['success']}
        strength_lbl = QLabel(f'Şifre gücü: {label}')
        strength_lbl.setStyleSheet(f'color: {colors_map[key]}; font-size: 11px; background: transparent;')
        pwd_row.addWidget(strength_lbl)

        lay.addLayout(pwd_row)

        if e.get('url'):
            self._add_field(lay, 'URL', e['url'], copyable=True)
        if e.get('notes'):
            self._add_field(lay, 'Notlar', e['notes'], multiline=True)

        # Tarihler
        dates = QLabel(
            f"Oluşturuldu: {e.get('created_at', '')[:19].replace('T', ' ')}   "
            f"Güncellendi: {e.get('modified_at', '')[:19].replace('T', ' ')}"
        )
        dates.setStyleSheet(f'color: {COLORS["text_muted"]}; font-size: 10px; background: transparent;')
        lay.addWidget(dates)

        close_btn = QPushButton('Kapat')
        close_btn.setStyleSheet(BUTTON_STYLE)
        close_btn.setMinimumHeight(44)
        close_btn.clicked.connect(self.accept)
        lay.addWidget(close_btn)

    def _add_field(self, lay, label, value, copyable=False, multiline=False):
        box = QVBoxLayout()
        lbl = QLabel(label)
        lbl.setStyleSheet(f'color: {COLORS["text_muted"]}; font-size: 11px; background: transparent;')
        box.addWidget(lbl)
        row = QHBoxLayout()
        if multiline:
            field = QTextEdit(value)
            field.setReadOnly(True)
            field.setFixedHeight(70)
            field.setStyleSheet(INPUT_STYLE)
        else:
            field = QLineEdit(value)
            field.setReadOnly(True)
            field.setStyleSheet(INPUT_STYLE)
        row.addWidget(field)
        if copyable:
            btn = QPushButton()
            btn.setIcon(_si(SP.SP_FileIcon, 20))
            btn.setIconSize(QSize(20, 20))
            btn.setFixedSize(40, 40)
            btn.setToolTip(f'{label} Kopyala')
            btn.setStyleSheet(BUTTON_SECONDARY_STYLE)
            btn.clicked.connect(lambda _, v=value: (
                QApplication.clipboard().setText(v),
                self._flash(btn, '✅')
            ))
            row.addWidget(btn)
        box.addLayout(row)
        lay.addLayout(box)

    @staticmethod
    def _flash(btn: QPushButton, text: str):
        orig = btn.text()
        btn.setText(text)
        QTimer.singleShot(1500, lambda: btn.setText(orig))


# ── ManagerWindow ──────────────────────────────────────────────────────────

class ManagerWindow(QWidget):
    """Phase 3 - Card-based password manager."""

    FILTERS = ['Tümü', '⭐ Favoriler', '⚠ Zayıf', '🗑 Çöp']

    _remote_update   = pyqtSignal()  # Mobil CRUD sonrası liste yenile
    logout_requested = pyqtSignal()  # Çıkış butonu → main'e bildir

    def __init__(self, vault):
        super().__init__()
        self.vault = vault
        self.network_server = None
        self.shared_secret = None
        self.shared_secret_b64 = None
        self.server_ip = None
        self._current_filter   = 'Tümü'
        self._current_category = ''   # '' = kategori filtresi yok
        self._search_text = ''
        self._entries = []
        self._card_widgets = []
        self._filter_btns: dict = {}  # label -> QPushButton
        self._cat_layout = None       # kategori butonları için layout
        self._remote_update.connect(self._load)
        self.setWindowTitle('Syncore')
        self.setMinimumSize(1000, 680)
        self._center()
        self._build_ui()
        self._load()
        self._start_server()

    # ── Layout ────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Top bar
        top = QWidget()
        top.setStyleSheet('background-color: rgba(23,23,23,0.92); border-bottom: 1px solid rgba(255,255,255,0.07);')
        top_lay = QHBoxLayout(top)
        top_lay.setContentsMargins(24, 16, 24, 16)

        title = QLabel(f'🔐  {_vault_title(self.vault.get_username())}')
        title.setStyleSheet(f'font-size: 22px; font-weight: bold; color: {COLORS["text_primary"]}; background: transparent;')
        top_lay.addWidget(title)
        top_lay.addStretch()

        self._counter_lbl = QLabel('0 şifre')
        self._counter_lbl.setStyleSheet(f'color: {COLORS["text_muted"]}; font-size: 13px; background: transparent;')
        top_lay.addWidget(self._counter_lbl)

        top_lay.addSpacing(16)

        logout_btn = QPushButton('Çıkış')
        logout_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: 1px solid {COLORS['border']};
                color: {COLORS['text_muted']}; border-radius: 8px;
                padding: 0 12px; font-size: 12px;
            }}
            QPushButton:hover {{ border-color: #ef4444; color: #ef4444; }}
        """)
        logout_btn.setMinimumHeight(40)
        logout_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        logout_btn.clicked.connect(self._on_logout)
        top_lay.addWidget(logout_btn)

        top_lay.addSpacing(8)

        add_btn = QPushButton('＋  Yeni Şifre')
        add_btn.setStyleSheet(BUTTON_STYLE)
        add_btn.setMinimumHeight(40)
        add_btn.clicked.connect(self._on_add)
        top_lay.addWidget(add_btn)

        root.addWidget(top)

        # Body: sidebar + content
        body = QHBoxLayout()
        body.setSpacing(0)
        body.setContentsMargins(0, 0, 0, 0)

        body.addWidget(self._build_sidebar())
        body.addWidget(self._build_content(), 1)

        body_widget = QWidget()
        body_widget.setLayout(body)
        body_widget.setStyleSheet(f'background-color: {COLORS["bg_primary"]};')
        root.addWidget(body_widget, 1)

        self.setStyleSheet(f'QWidget {{ background-color: {COLORS["bg_primary"]}; color: {COLORS["text_primary"]}; font-family: "Segoe UI Emoji", "Segoe UI", Arial, sans-serif; }}')

    def _build_sidebar(self):
        side = QWidget()
        side.setFixedWidth(200)
        side.setStyleSheet('background-color: rgba(23,23,23,0.88); border-right: 1px solid rgba(255,255,255,0.06);')
        lay = QVBoxLayout(side)
        lay.setContentsMargins(12, 20, 12, 20)
        lay.setSpacing(6)

        lbl = QLabel('FİLTRELE')
        lbl.setStyleSheet(f'color: {COLORS["text_muted"]}; font-size: 10px; letter-spacing: 1px; background: transparent;')
        lay.addWidget(lbl)
        lay.addSpacing(6)

        self._chip_group = QButtonGroup(self)
        self._chip_group.setExclusive(True)

        for i, name in enumerate(self.FILTERS):
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setStyleSheet(CHIP_BUTTON_STYLE)
            btn.setMinimumHeight(38)
            if i == 0:
                btn.setChecked(True)
            btn.clicked.connect(lambda checked, n=name: self._on_filter(n))
            self._chip_group.addButton(btn)
            self._filter_btns[name] = btn
            lay.addWidget(btn)

        # Ayraç
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet('color: rgba(255,255,255,0.08); background: rgba(255,255,255,0.08);')
        sep.setFixedHeight(1)
        lay.addSpacing(8)
        lay.addWidget(sep)
        lay.addSpacing(4)

        cat_lbl = QLabel('KATEGORİ')
        cat_lbl.setStyleSheet(f'color: {COLORS["text_muted"]}; font-size: 10px; letter-spacing: 1px; background: transparent;')
        lay.addWidget(cat_lbl)
        lay.addSpacing(4)

        # Dinamik kategori butonları için scroll area
        cat_scroll = QScrollArea()
        cat_scroll.setWidgetResizable(True)
        cat_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        cat_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        cat_scroll.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QScrollArea > QWidget > QWidget { background: transparent; }
            QScrollBar:vertical { background: transparent; width: 4px; }
            QScrollBar::handle:vertical { background: rgba(255,255,255,0.15); border-radius: 2px; }
        """)

        cat_container = QWidget()
        cat_container.setStyleSheet('background: transparent;')
        self._cat_layout = QVBoxLayout(cat_container)
        self._cat_layout.setContentsMargins(0, 0, 0, 0)
        self._cat_layout.setSpacing(4)
        self._cat_layout.addStretch()
        cat_scroll.setWidget(cat_container)
        lay.addWidget(cat_scroll, 1)

        # 2FA server status
        self._status_lbl = QLabel('⬤  Bağlanıyor...')
        self._status_lbl.setWordWrap(True)
        self._status_lbl.setStyleSheet(f'color: {COLORS["text_muted"]}; font-size: 11px; background: transparent;')
        lay.addWidget(self._status_lbl)

        qr_btn = QPushButton('  QR Eşleştir')
        qr_btn.setIcon(_si(SP.SP_ComputerIcon, 18))
        qr_btn.setIconSize(QSize(18, 18))
        qr_btn.setStyleSheet(BUTTON_SECONDARY_STYLE)
        qr_btn.setMinimumHeight(38)
        qr_btn.clicked.connect(self._show_qr_dialog)
        lay.addWidget(qr_btn)

        return side

    def _build_content(self):
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(14)

        # Search
        self._search = QLineEdit()
        self._search.setPlaceholderText('🔍  Şifre ara...')
        self._search.setStyleSheet(SEARCH_BAR_STYLE)
        self._search.setMinimumHeight(44)
        self._search.textChanged.connect(self._on_search)
        lay.addWidget(self._search)

        # Card scroll area
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(SCROLL_AREA_STYLE)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._card_container = QWidget()
        self._card_container.setStyleSheet('background: transparent;')
        self._card_layout = QVBoxLayout(self._card_container)
        self._card_layout.setSpacing(10)
        self._card_layout.setContentsMargins(0, 0, 8, 0)
        self._card_layout.addStretch()

        self._scroll.setWidget(self._card_container)
        lay.addWidget(self._scroll)

        return content

    # ── Data ──────────────────────────────────────────────────────────────

    def _load(self):
        try:
            fav_only   = self._current_filter == '⭐ Favoriler'
            trash_only = self._current_filter == '🗑 Çöp'

            if self._current_filter == '⚠ Zayıf':
                all_entries = self.vault.get_all_passwords()
                weak = []
                for e in all_entries:
                    try:
                        pwd = self.vault.get_password(e['id'])
                        _, _, strength = score_password(pwd or '')
                        if strength == 'weak':
                            e['_password_preview'] = pwd
                            weak.append(e)
                    except Exception:
                        pass
                self._entries = weak
            else:
                self._entries = self.vault.get_all_passwords(
                    favorites_only=fav_only,
                    trashed_only=trash_only
                )

            # Kategori filtresi
            if self._current_category:
                self._entries = [
                    e for e in self._entries
                    if get_category(e['title']) and
                       get_category(e['title'])[0] == self._current_category
                ]

            # Her entry'e kategori bilgisi ekle
            for e in self._entries:
                e['_category'] = get_category(e['title'])

            self._rebuild_category_buttons()
            self._render_cards()
        except Exception as ex:
            QMessageBox.critical(self, 'Hata', str(ex))

    def _render_cards(self):
        # Mevcut kartları anında gizle ve sil
        for w in self._card_widgets:
            w.hide()
            w.deleteLater()
        self._card_widgets.clear()

        entries = self._entries
        in_trash = self._current_filter == '🗑 Çöp'

        if self._search_text:
            q = self._search_text.lower()
            entries = [e for e in entries if q in (e['title'] or '').lower()]

        # Layout'taki stretch dışındaki tüm item'ları temizle
        while self._card_layout.count() > 1:
            self._card_layout.takeAt(0)

        if not entries:
            empty = QLabel(
                'Sonuç bulunamadı.' if self._search_text
                else 'Henüz şifre yok. Yeni şifre eklemek için  Yeni Şifre  butonuna tıklayın.'
            )
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(f'color: {COLORS["text_muted"]}; font-size: 14px; background: transparent;')
            self._card_layout.insertWidget(0, empty)
        else:
            for e in entries:
                card = PasswordCard(e, in_trash=in_trash)
                card.sig_view.connect(self._on_view)
                card.sig_copy.connect(self._on_copy)
                card.sig_edit.connect(self._on_edit)
                card.sig_delete.connect(self._on_delete)
                card.sig_favorite.connect(self._on_favorite)
                card.sig_trash.connect(self._on_trash)
                card.sig_restore.connect(self._on_restore)
                self._card_layout.insertWidget(self._card_layout.count() - 1, card)
                self._card_widgets.append(card)

        total = self.vault.get_all_passwords()
        self._counter_lbl.setText(f'{len(total)} şifre')

    # ── Filter & Search ───────────────────────────────────────────────────

    def _on_filter(self, name):
        self._current_filter   = name
        self._current_category = ''
        self._load()

    def _on_category(self, name: str):
        self._current_category = name
        self._current_filter   = 'Tümü'
        # Filtre chiplerini 'Tümü'ye sıfırla
        btn = self._filter_btns.get('Tümü')
        if btn:
            self._chip_group.blockSignals(True)
            btn.setChecked(True)
            self._chip_group.blockSignals(False)
        self._load()

    def _rebuild_category_buttons(self):
        if self._cat_layout is None:
            return
        # Mevcut butonları temizle (stretch hariç)
        while self._cat_layout.count() > 1:
            item = self._cat_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Tüm şifrelerdeki kategorileri say
        try:
            all_entries = self.vault.get_all_passwords()
        except Exception:
            return
        counts: dict = {}
        for e in all_entries:
            cat = get_category(e['title'])
            if cat:
                counts[cat] = counts.get(cat, 0) + 1

        if not counts:
            empty = QLabel('Henüz kategori yok')
            empty.setStyleSheet(f'color: {COLORS["text_muted"]}; font-size: 10px; background: transparent;')
            self._cat_layout.insertWidget(0, empty)
            return

        for (name, emoji), count in sorted(counts.items(), key=lambda x: -x[1]):
            btn = QPushButton(f'{emoji} {name}  {count}')
            btn.setCheckable(True)
            btn.setChecked(self._current_category == name)
            btn.setStyleSheet(CHIP_BUTTON_STYLE)
            btn.setMinimumHeight(34)
            btn.clicked.connect(lambda _, n=name: self._on_category(n))
            self._cat_layout.insertWidget(self._cat_layout.count() - 1, btn)

    def _on_search(self, text):
        self._search_text = text
        self._render_cards()

    # ── CRUD ──────────────────────────────────────────────────────────────

    def _on_view(self, entry_id):
        """Kart tıklandığında şifre detaylarını göster."""
        try:
            entry = next(e for e in self._entries if e['id'] == entry_id)
            pwd = self.vault.get_password(entry_id)
            dlg = ViewPasswordDialog(entry, pwd, parent=self)
            dlg.exec()
        except StopIteration:
            pass
        except Exception as ex:
            QMessageBox.critical(self, 'Hata', str(ex))

    def _on_logout(self):
        from session_manager import clear_session
        clear_session()
        self._stop_server()
        self.logout_requested.emit()
        self.close()

    def _stop_server(self):
        if self.network_server:
            try:
                self.network_server.stop()
            except Exception:
                pass
            self.network_server = None

    def _notify_mobile(self):
        """Desktop CRUD sonrası bağlı mobilin listesini güncelle."""
        if self.network_server:
            self.network_server.mark_data_changed()

    def _on_add(self):
        dlg = AddPasswordDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            d = dlg.get_data()
            try:
                self.vault.add_password(**d)
                self._load()
                self._notify_mobile()
            except Exception as ex:
                QMessageBox.critical(self, 'Hata', str(ex))

    def _on_copy(self, entry_id):
        try:
            pwd = self.vault.get_password(entry_id)
            QApplication.clipboard().setText(pwd)
            self._flash_status('📋 Şifre kopyalandı!')
        except Exception as ex:
            QMessageBox.critical(self, 'Hata', str(ex))

    def _on_edit(self, entry_id):
        try:
            entry = next(e for e in self._entries if e['id'] == entry_id)
            entry['password'] = self.vault.get_password(entry_id)
            dlg = AddPasswordDialog(self, edit_mode=True, entry_data=entry)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                d = dlg.get_data()
                self.vault.update_password(entry_id, **d)
                self._load()
                self._notify_mobile()
        except Exception as ex:
            QMessageBox.critical(self, 'Hata', str(ex))

    def _on_delete(self, entry_id):
        if _confirm(self, 'Kalıcı Sil', 'Bu şifreyi kalıcı olarak silmek istiyor musunuz?'):
            self.vault.delete_password(entry_id)
            self._load()
            self._notify_mobile()

    def _on_favorite(self, entry_id):
        self.vault.toggle_favorite(entry_id)
        self._load()
        self._notify_mobile()

    def _on_trash(self, entry_id):
        self.vault.trash_password(entry_id)
        self._load()
        self._notify_mobile()

    def _on_restore(self, entry_id):
        self.vault.restore_password(entry_id)
        self._load()
        self._notify_mobile()

    # Network / 2FA

    def _start_server(self):
        try:
            self.network_server = NetworkServer()
            self.network_server.start()
            self.shared_secret = self.vault.get_network_secret()
            username = self.vault.get_username()

            def _on_auth(success, _device_id, _username='', _secret=''):
                if not success:
                    print("[Manager] Mobil auth başarısız")

            self.network_server.set_auto_challenge(
                self.shared_secret, _on_auth, expected_username=username
            )
            self.network_server.set_vault(
                self.vault,
                on_data_changed=lambda: self._remote_update.emit()
            )
            self.shared_secret_b64 = base64.b64encode(self.shared_secret).decode()
            self.server_ip = self.network_server.get_server_ip()
            self._status_lbl.setText('⬤  Sunucu Bağlı')
            self._status_lbl.setToolTip(f'{self.server_ip}:8765')
            self._status_lbl.setStyleSheet(
                f'color: {COLORS["success"]}; font-size: 11px; background: transparent;')
        except Exception as ex:
            self._status_lbl.setText('⬤  Sunucu Hatası')
            self._status_lbl.setToolTip(str(ex))
            self._status_lbl.setStyleSheet(
                f'color: {COLORS["danger"]}; font-size: 11px; background: transparent;')

    def _show_qr_dialog(self):
        dlg = QRPairingDialog(self.server_ip, self.shared_secret_b64, parent=self)
        dlg.exec()

    def _flash_status(self, msg):
        self._status_lbl.setText(msg)
        QTimer.singleShot(2500, lambda: self._status_lbl.setText('⬤  Sunucu Bağlı'))

    def _center(self):
        from PyQt6.QtGui import QScreen
        scr = QScreen.availableGeometry(self.screen())
        self.move((scr.width() - self.width()) // 2, (scr.height() - self.height()) // 2)

    def showEvent(self, event):
        super().showEvent(event)
        _dark_titlebar(self)

    def closeEvent(self, event):
        if self.network_server:
            try: self.network_server.stop()
            except: pass
        event.accept()


# QR Pairing Dialog

class QRPairingDialog(QDialog):
    def __init__(self, server_ip, secret_b64, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Mobil Cihaz Eşleştir')
        self.setFixedSize(480, 580)
        self.setModal(True)
        self.setStyleSheet(f'QDialog {{ background-color: {COLORS["bg_primary"]}; }}')
        self._build(server_ip, secret_b64)

    def showEvent(self, event):
        super().showEvent(event)
        _dark_titlebar(self)

    def _build(self, ip, secret):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 32, 32, 32)
        lay.setSpacing(16)

        title = QLabel('Mobil Eslestirme')
        title.setStyleSheet(LABEL_TITLE_STYLE)
        lay.addWidget(title)

        sub = QLabel('Mobil uygulamada asagidaki bilgileri girin:')
        sub.setStyleSheet(LABEL_SUBTITLE_STYLE)
        lay.addWidget(sub)

        qr_lbl = QLabel()
        qr_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qr_lbl.setFixedHeight(220)

        if ip and secret:
            try:
                import qrcode, io
                from urllib.parse import quote as _quote
                data = f'pvault://{ip}:8765?secret={_quote(secret, safe="")}'
                qr = qrcode.QRCode(box_size=6, border=2)
                qr.add_data(data)
                qr.make(fit=True)
                img = qr.make_image(fill_color='white', back_color='#1f1b2e')
                buf = io.BytesIO()
                img.save(buf, format='PNG')
                buf.seek(0)
                pix = QPixmap()
                pix.loadFromData(buf.read())
                qr_lbl.setPixmap(pix.scaled(200, 200,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation))
            except ImportError:
                qr_lbl.setText('qrcode kutuphanesi yuklu degil\npip install qrcode[pil]')
                qr_lbl.setStyleSheet(f'color: {COLORS["warning"]}; font-size: 13px;')
        else:
            qr_lbl.setText('Server baslatilmadi')
            qr_lbl.setStyleSheet(f'color: {COLORS["danger"]};')

        qr_frame = QWidget()
        qr_frame.setStyleSheet(
            f'background-color: {COLORS["bg_secondary"]}; '
            f'border: 1px solid {COLORS["border"]}; border-radius: 12px;')
        QVBoxLayout(qr_frame).addWidget(qr_lbl)
        lay.addWidget(qr_frame)

        for label, value in [
            ('Server IP', f'{ip}:8765' if ip else '-'),
            ('Shared Secret', secret or '-')
        ]:
            row = QVBoxLayout()
            lbl = QLabel(label)
            lbl.setStyleSheet(
                f'color: {COLORS["text_secondary"]}; font-size: 11px; background: transparent;')
            row.addWidget(lbl)
            field = QLineEdit(value)
            field.setReadOnly(True)
            field.setStyleSheet(INPUT_STYLE)
            copy_btn = QPushButton('Kopyala')
            copy_btn.setStyleSheet(BUTTON_SECONDARY_STYLE)
            copy_btn.setFixedHeight(32)
            copy_btn.clicked.connect(lambda _, v=value: QApplication.clipboard().setText(v))
            row.addWidget(field)
            row.addWidget(copy_btn)
            lay.addLayout(row)

        close_btn = QPushButton('Kapat')
        close_btn.setStyleSheet(BUTTON_STYLE)
        close_btn.setMinimumHeight(44)
        close_btn.clicked.connect(self.accept)
        lay.addWidget(close_btn)
