import sys
import tempfile
import os
from PyQt6.QtWidgets import QApplication

from ui.manager_window import ManagerWindow
from ui.styles import get_complete_style
from vault_storage import VaultStorage

def main():
    app = QApplication(sys.argv)
    app.setApplicationName('Password Vault Test')
    app.setStyleSheet(get_complete_style())

    temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
    temp_db.close()

    vault = VaultStorage(temp_db.name)
    vault.initialize_vault("testpass123!")
    vault.unlock_vault("testpass123!")

    # Örnek veriler ekleyelim
    vault.add_password("Gmail", "john.doe@gmail.com", "secret123", "https://gmail.com", "Personal email")
    vault.add_password("GitHub", "johndoe", "token_abc123", "https://github.com")
    vault.add_password("Netflix", "john.doe@gmail.com", "netflixpass", "https://netflix.com")

    window = ManagerWindow(vault)
    window.show()

    ret = app.exec()
    
    vault.close()
    os.unlink(temp_db.name)
    sys.exit(ret)

if __name__ == '__main__':
    main()
