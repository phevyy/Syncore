"""
UI Styles - Modern Dark Theme
================================

Password Vault için modern dark theme stil tanımları.
Her UI bileşeni bu dosyayı import ederek tutarlı görünüm sağlar.
"""

# Color Palette (Stitch Design - Dark Mode)
COLORS = {
    # Background Colors (from Stitch)
    'bg_primary': '#0A0A0A',      # Deep black (Stitch Login)
    'bg_secondary': '#171717',    # Surface dark (Stitch)
    'bg_tertiary': '#2d2335',     # Card background (Stitch Main)
    'bg_input': '#1f1b2e',        # Input fields
    'bg_surface': '#251e2b',      # Vault cards (Stitch Main)
    
    # Accent Colors (Stitch Purple Theme)
    'accent': '#7a2bbf',          # Primary purple (Stitch)
    'accent_hover': '#9D4EDD',    # Primary light (Stitch)
    'accent_light': '#a78bfa',    # Light purple
    'accent_dark': '#5e2194',     # Dark purple (Stitch Main)
    
    # Text Colors
    'text_primary': '#f3f4f6',    # White/light text
    'text_secondary': '#af99c2',  # Purple-tinted gray (Stitch)
    'text_muted': '#6b7280',      # Muted gray
    
    # Status Colors
    'success': '#10b981',         # Green (strong password)
    'danger': '#ef4444',          # Red (weak password)
    'warning': '#f59e0b',         # Orange/Yellow (medium)
    'info': '#3b82f6',            # Blue
    
    # Border Colors
    'border': '#2A2A2A',          # Border dark (Stitch)
    'border_focus': '#7a2bbf',    # Focus border (primary)
    'border_light': '#3f3f46',    # Light border
}

# Main Application Style
MAIN_STYLE = f"""
QWidget {{
    background-color: {COLORS['bg_primary']};
    color: {COLORS['text_primary']};
    font-family: 'Segoe UI Emoji', 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
}}

QMainWindow {{
    background-color: {COLORS['bg_primary']};
}}
"""

# Button Styles (Gradient - Stitch Design)
BUTTON_STYLE = f"""
QPushButton {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 {COLORS['accent']},
                                stop:1 {COLORS['accent_hover']});
    color: {COLORS['text_primary']};
    border: none;
    border-radius: 10px;
    padding: 12px 24px;
    font-weight: bold;
    font-size: 14px;
    letter-spacing: 1px;
    font-family: 'Segoe UI Emoji', 'Segoe UI', Arial, sans-serif;
}}

QPushButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 {COLORS['accent_hover']},
                                stop:1 {COLORS['accent_light']});
}}

QPushButton:pressed {{
    background-color: {COLORS['accent_dark']};
    padding: 13px 23px 11px 25px;
}}

QPushButton:disabled {{
    background-color: {COLORS['bg_tertiary']};
    color: {COLORS['text_muted']};
}}
"""

# Secondary Button (Outlined)
BUTTON_SECONDARY_STYLE = f"""
QPushButton {{
    background-color: transparent;
    color: {COLORS['text_primary']};
    border: 2px solid {COLORS['border']};
    border-radius: 8px;
    padding: 10px 20px;
    font-weight: bold;
    font-size: 13px;
    font-family: 'Segoe UI Emoji', 'Segoe UI', Arial, sans-serif;
}}

QPushButton:hover {{
    border-color: {COLORS['accent']};
    color: {COLORS['accent']};
}}

QPushButton:pressed {{
    background-color: {COLORS['bg_tertiary']};
}}
"""

# Danger Button
BUTTON_DANGER_STYLE = f"""
QPushButton {{
    background-color: {COLORS['danger']};
    color: {COLORS['text_primary']};
    border: none;
    border-radius: 8px;
    padding: 10px 20px;
    font-weight: bold;
    font-size: 13px;
}}

QPushButton:hover {{
    background-color: #dc2626;
}}
"""

# Input/LineEdit Styles
INPUT_STYLE = f"""
QLineEdit {{
    background-color: {COLORS['bg_input']};
    color: {COLORS['text_primary']};
    border: 2px solid {COLORS['border']};
    border-radius: 8px;
    padding: 10px 15px;
    font-size: 13px;
}}

QLineEdit:focus {{
    border-color: {COLORS['border_focus']};
}}

QLineEdit:disabled {{
    background-color: {COLORS['bg_tertiary']};
    color: {COLORS['text_muted']};
}}
"""

# Table Widget Styles
TABLE_STYLE = f"""
QTableWidget {{
    background-color: {COLORS['bg_secondary']};
    color: {COLORS['text_primary']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    gridline-color: {COLORS['border']};
    selection-background-color: {COLORS['accent']};
    selection-color: {COLORS['text_primary']};
}}

QTableWidget::item {{
    padding: 8px;
}}

QTableWidget::item:selected {{
    background-color: {COLORS['accent']};
}}

QHeaderView::section {{
    background-color: {COLORS['bg_tertiary']};
    color: {COLORS['text_secondary']};
    border: none;
    border-bottom: 2px solid {COLORS['border']};
    padding: 10px;
    font-weight: bold;
}}

QScrollBar:vertical {{
    background-color: {COLORS['bg_secondary']};
    width: 12px;
    border-radius: 6px;
}}

QScrollBar::handle:vertical {{
    background-color: {COLORS['bg_tertiary']};
    border-radius: 6px;
    min-height: 20px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {COLORS['accent']};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
"""

# Label Styles
LABEL_STYLE = f"""
QLabel {{
    color: {COLORS['text_primary']};
    background-color: transparent;
}}
"""

LABEL_TITLE_STYLE = f"""
QLabel {{
    color: {COLORS['text_primary']};
    font-size: 24px;
    font-weight: bold;
    background-color: transparent;
}}
"""

LABEL_SUBTITLE_STYLE = f"""
QLabel {{
    color: {COLORS['text_secondary']};
    font-size: 14px;
    background-color: transparent;
}}
"""

# Icon Button Style (Circular)
ICON_BUTTON_STYLE = f"""
QPushButton {{
    background-color: {COLORS['accent']};
    color: {COLORS['text_primary']};
    border: none;
    border-radius: 20px;
    padding: 10px;
    min-width: 40px;
    min-height: 40px;
    max-width: 40px;
    max-height: 40px;
    font-size: 18px;
}}

QPushButton:hover {{
    background-color: {COLORS['accent_hover']};
}}

QPushButton:pressed {{
    background-color: {COLORS['accent_dark']};
}}
"""

# Card Style (for password entries)
CARD_STYLE = f"""
QWidget {{
    background-color: {COLORS['bg_surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 16px;
    padding: 12px;
}}
"""

# Card Style - Hover state (applied programmatically)
CARD_STYLE_HOVER = f"""
QWidget {{
    background-color: {COLORS['bg_tertiary']};
    border: 1px solid {COLORS['accent']};
    border-radius: 16px;
    padding: 12px;
}}
"""

# Strength Bar Styles
STRENGTH_WEAK_STYLE = f"""
QProgressBar {{
    background-color: {COLORS['bg_tertiary']};
    border: none;
    border-radius: 4px;
    height: 6px;
}}
QProgressBar::chunk {{
    background-color: {COLORS['danger']};
    border-radius: 4px;
}}
"""

STRENGTH_MEDIUM_STYLE = f"""
QProgressBar {{
    background-color: {COLORS['bg_tertiary']};
    border: none;
    border-radius: 4px;
    height: 6px;
}}
QProgressBar::chunk {{
    background-color: {COLORS['warning']};
    border-radius: 4px;
}}
"""

STRENGTH_STRONG_STYLE = f"""
QProgressBar {{
    background-color: {COLORS['bg_tertiary']};
    border: none;
    border-radius: 4px;
    height: 6px;
}}
QProgressBar::chunk {{
    background-color: {COLORS['success']};
    border-radius: 4px;
}}
"""

# QR Code Panel Style
QR_PANEL_STYLE = f"""
QWidget {{
    background-color: {COLORS['bg_secondary']};
    border: 1px solid {COLORS['border']};
    border-radius: 12px;
    padding: 16px;
}}
"""

# Scroll Area Style
SCROLL_AREA_STYLE = f"""
QScrollArea {{
    border: none;
    background-color: transparent;
}}
QScrollArea > QWidget > QWidget {{
    background-color: transparent;
}}
QScrollBar:vertical {{
    background-color: {COLORS['bg_secondary']};
    width: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background-color: {COLORS['bg_tertiary']};
    border-radius: 4px;
    min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{
    background-color: {COLORS['accent']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
"""

# Search Bar Style
SEARCH_BAR_STYLE = f"""
QLineEdit {{
    background-color: {COLORS['bg_tertiary']};
    color: {COLORS['text_primary']};
    border: 2px solid {COLORS['border']};
    border-radius: 12px;
    padding: 12px 15px 12px 45px;
    font-size: 14px;
}}

QLineEdit:focus {{
    border-color: {COLORS['border_focus']};
    background-color: {COLORS['bg_input']};
}}
"""

# Chip Button Style (for filters) - inactive
CHIP_BUTTON_STYLE = f"""
QPushButton {{
    background-color: {COLORS['bg_tertiary']};
    color: {COLORS['text_secondary']};
    border: 1px solid {COLORS['border']};
    border-radius: 18px;
    padding: 8px 18px;
    font-size: 13px;
    font-weight: 500;
}}

QPushButton:hover {{
    border-color: {COLORS['accent']};
    color: {COLORS['accent_light']};
}}

QPushButton:checked {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 {COLORS['accent']},
                                stop:1 {COLORS['accent_hover']});
    color: {COLORS['text_primary']};
    border-color: {COLORS['accent']};
    font-weight: bold;
}}
"""

# Dialog Styles
DIALOG_STYLE = f"""
QDialog {{
    background-color: {COLORS['bg_primary']};
}}

QMessageBox {{
    background-color: {COLORS['bg_primary']};
}}

QMessageBox QLabel {{
    color: {COLORS['text_primary']};
}}

QMessageBox QPushButton {{
    min-width: 80px;
}}
"""

# Complete Application Style (combines all)
def get_complete_style():
    """Tüm stilleri birleştirerek döndürür."""
    return f"""
{MAIN_STYLE}
{BUTTON_STYLE}
{INPUT_STYLE}
{TABLE_STYLE}
{LABEL_STYLE}
{DIALOG_STYLE}
"""
