"""
Vault Storage Manager - Şifreli Veritabanı Yöneticisi
======================================================

SQLite veritabanında şifrelerin güvenli saklanması.
Her şifre entry'si AES-256-GCM ile şifrelenir.

Veritabanı Şeması:
- vault_config: Ana parola hash, salt, sistem ayarları
- password_entries: Şifreli password verileri
- device_pairs: Eşleşmiş mobil cihazlar (shared secrets)
"""

import sqlite3
import json
import base64
import hashlib
import os
import threading
import uuid as _uuid_mod
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Tuple
from pathlib import Path

from crypto_manager import PasswordCrypto, KeyDerivation


class VaultStorage:
    """
    Şifreli password vault veritabanı yöneticisi.
    
    Güvenlik Özellikleri:
    - Her password entry ayrı ayrı şifrelenir (unique nonce)
    - Ana parola asla saklanmaz, sadece verification hash
    - Shared secrets için ayrı tablo
    - Timestamp tracking (oluşturma/değiştirme zamanı)
    """
    
    @staticmethod
    def get_user_db_path(username: str) -> str:
        """Kullanıcıya özgü veritabanı dizinini döner."""
        vault_dir = Path.home() / ".password_vault" / username
        vault_dir.mkdir(parents=True, exist_ok=True)
        return str(vault_dir / "vault.db")

    def __init__(self, db_path: str = None):
        """
        Args:
            db_path: Veritabanı dosya yolu (default: vault.db)
        """
        if db_path is None:
            # Varsayılan: kullanıcının home dizininde
            home = Path.home()
            vault_dir = home / ".password_vault"
            vault_dir.mkdir(exist_ok=True)
            db_path = str(vault_dir / "vault.db")
        
        self.db_path = db_path
        self.conn = None
        self._lock = threading.Lock()   # Çok-thread SQLite erişimi için
        self.crypto = None
        self.username: str = ''
        self.network_secret: bytes = b''
        self.kdf = KeyDerivation()
        
        # Veritabanı başlat
        self._initialize_database()
    
    def _initialize_database(self):
        """Veritabanı tablolarını oluşturur (ilk çalıştırmada)."""
        # check_same_thread=False: arka plan thread'lerinden de erişim için
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        cursor = self.conn.cursor()
        
        # 1. Vault yapılandırması (tek satır)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS vault_config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                master_password_hash TEXT NOT NULL,
                master_password_salt BLOB NOT NULL,
                created_at TEXT NOT NULL,
                last_login TEXT
            )
        """)
        
        # 2. Şifre girişleri
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS password_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                username TEXT,
                encrypted_password BLOB NOT NULL,
                nonce BLOB NOT NULL,
                url TEXT,
                notes TEXT,
                is_favorite INTEGER DEFAULT 0,
                is_trashed INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                modified_at TEXT NOT NULL
            )
        """)

        # 4. Kalıcı silme tombstone tablosu (sync için)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS deleted_uuids (
                uuid       TEXT PRIMARY KEY,
                deleted_at TEXT NOT NULL
            )
        """)

        # Migration: yeni sütunları mevcut veritabanlarına ekle
        for col, default in [("is_favorite", 0), ("is_trashed", 0)]:
            try:
                cursor.execute(f"ALTER TABLE password_entries ADD COLUMN {col} INTEGER DEFAULT {default}")
            except Exception:
                pass
        try:
            cursor.execute("ALTER TABLE vault_config ADD COLUMN username TEXT DEFAULT ''")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE password_entries ADD COLUMN uuid TEXT DEFAULT ''")
        except Exception:
            pass
        
        # 3. Eşleşmiş mobil cihazlar
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS device_pairs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_name TEXT NOT NULL,
                shared_secret BLOB NOT NULL,
                paired_at TEXT NOT NULL,
                last_used TEXT
            )
        """)
        
        self.conn.commit()
    
    def is_initialized(self) -> bool:
        """Vault daha önce kurulmuş mu kontrol eder."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM vault_config")
        count = cursor.fetchone()[0]
        return count > 0
    
    def initialize_vault(self, username: str, master_password: str) -> bool:
        """Yeni vault oluşturur. username + master_password ile."""
        if self.is_initialized():
            raise RuntimeError("Vault zaten başlatılmış!")
        if not username.strip():
            raise ValueError("Kullanıcı adı boş olamaz.")

        verification_hash = self.kdf.create_verification_hash(master_password)
        _, salt = self.kdf.derive_key(master_password)

        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO vault_config (id, username, master_password_hash, master_password_salt, created_at)
            VALUES (1, ?, ?, ?, ?)
        """, (username.strip(), verification_hash, salt, datetime.utcnow().isoformat() + 'Z'))
        self.conn.commit()
        return True
    
    def unlock_vault(self, username: str, master_password: str) -> bool:
        """Vault kilidini açar. username + master_password doğrular."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT username, master_password_hash, master_password_salt FROM vault_config WHERE id = 1"
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("Vault başlatılmamış!")

        stored_username = row['username'] or ''
        # Mevcut vault'larda username boşsa kabul et ve kaydet (migration)
        if stored_username and stored_username != username.strip():
            return False

        if not self.kdf.verify_password(row['master_password_hash'], master_password):
            return False

        key, _ = self.kdf.derive_key(master_password, row['master_password_salt'])
        self.crypto = PasswordCrypto(key)
        self.username = username.strip()
        self.network_secret = hashlib.sha256(master_password.encode('utf-8')).digest()

        # Eski vault'lara username yaz
        if not stored_username:
            cursor.execute("UPDATE vault_config SET username = ? WHERE id = 1", (self.username,))
        cursor.execute("UPDATE vault_config SET last_login = ? WHERE id = 1",
                       (datetime.utcnow().isoformat() + 'Z',))
        self.conn.commit()
        self._ensure_uuids()
        return True

    def delete_account(self) -> None:
        """Tüm kullanıcı verilerini ve hesabı veritabanından siler."""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM vault_config")
        cursor.execute("DELETE FROM password_entries")
        cursor.execute("DELETE FROM device_pairs")
        self.conn.commit()
        self.crypto         = None
        self.username       = ''
        self.network_secret = b''

    def unlock_or_create_with_network_secret(
            self, username: str, network_secret: bytes) -> bool:
        """
        Mobile-first akış: SHA-256(password) bytes ile vault'u aç veya oluştur.
        Argon2 gerektirmez; network_secret doğrudan AES-256 anahtarı olarak kullanılır.
        """
        if len(network_secret) != 32:
            return False
        verification = hashlib.sha256(network_secret).hexdigest()

        if not self.is_initialized():
            # Yeni vault: SHA-256 tabanlı
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO vault_config
                (id, username, master_password_hash, master_password_salt, created_at)
                VALUES (1, ?, ?, ?, ?)
            """, (username.strip(), verification,
                  b'sha256_direct', datetime.utcnow().isoformat() + 'Z'))
            self.conn.commit()
        else:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT username, master_password_hash, master_password_salt "
                "FROM vault_config WHERE id = 1"
            )
            row = cursor.fetchone()
            if row is None:
                return False
            salt = bytes(row['master_password_salt']) if row['master_password_salt'] else b''
            if salt != b'sha256_direct':
                # Argon2 vault — SHA-256'ya migrate et (eski şifreler silinir)
                cursor.execute("DELETE FROM vault_config")
                cursor.execute("DELETE FROM password_entries")
                cursor.execute("DELETE FROM deleted_uuids")
                cursor.execute("""
                    INSERT INTO vault_config
                    (id, username, master_password_hash, master_password_salt, created_at)
                    VALUES (1, ?, ?, ?, ?)
                """, (username.strip(), verification,
                      b'sha256_direct', datetime.utcnow().isoformat() + 'Z'))
                self.conn.commit()
            else:
                stored_username = row['username'] or ''
                if stored_username and stored_username != username.strip():
                    return False
                if row['master_password_hash'] != verification:
                    return False

        self.crypto         = PasswordCrypto(network_secret)
        self.username       = username.strip()
        self.network_secret = network_secret
        cursor = self.conn.cursor()
        cursor.execute("UPDATE vault_config SET last_login = ? WHERE id = 1",
                       (datetime.utcnow().isoformat() + 'Z',))
        self.conn.commit()
        self._ensure_uuids()
        return True

    def _ensure_uuids(self):
        """UUID'si olmayan mevcut entrylara UUID ata."""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT id FROM password_entries WHERE uuid IS NULL OR uuid = ''")
            rows = cursor.fetchall()
            for row in rows:
                cursor.execute("UPDATE password_entries SET uuid = ? WHERE id = ?",
                               (str(_uuid_mod.uuid4()), row['id']))
            if rows:
                self.conn.commit()

    def get_username(self) -> str:
        return self.username

    def get_network_secret(self) -> bytes:
        """SHA-256(master_password) — mobil HMAC auth için shared secret."""
        return self.network_secret
    
    def add_password(self, title: str, username: str, password: str,
                     url: str = "", notes: str = "", uuid: str = None) -> int:
        """
        Yeni şifre girişi ekler.

        Args:
            title: Başlık (örn: "Gmail")
            username: Kullanıcı adı veya email
            password: Kaydedilecek şifre
            url: Website URL (opsiyonel)
            notes: Notlar (opsiyonel)

        Returns:
            Eklenen entry'nin ID'si
        """
        if self.crypto is None:
            raise RuntimeError("Vault kilidi açık değil! Önce unlock_vault() çağırın.")

        encrypted_password, nonce = self.crypto.encrypt(password)
        now = datetime.utcnow().isoformat() + 'Z'
        entry_uuid = uuid if uuid else str(_uuid_mod.uuid4())
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO password_entries
                (uuid, title, username, encrypted_password, nonce, url, notes, is_favorite, is_trashed, created_at, modified_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)
            """, (entry_uuid, title, username, encrypted_password, nonce, url, notes, now, now))
            self.conn.commit()
            return cursor.lastrowid
    
    def get_all_passwords(self, favorites_only=False, trashed_only=False) -> List[Dict]:
        """Tüm şifre girişlerini listeler (şifreler hariç, sadece metadata)."""
        if self.crypto is None:
            raise RuntimeError("Vault kilidi açık değil!")

        with self._lock:
            cursor = self.conn.cursor()

            if trashed_only:
                where = "WHERE is_trashed = 1"
            elif favorites_only:
                where = "WHERE is_favorite = 1 AND is_trashed = 0"
            else:
                where = "WHERE is_trashed = 0"

            cursor.execute(f"""
                SELECT id, uuid, title, username, url, notes, is_favorite, is_trashed, created_at, modified_at
                FROM password_entries
                {where}
                ORDER BY title ASC
            """)

            entries = []
            for row in cursor.fetchall():
                entries.append({
                    'id': row['id'],
                    'uuid': row['uuid'] or '',
                    'title': row['title'],
                    'username': row['username'],
                    'url': row['url'] or '',
                    'notes': row['notes'] or '',
                    'is_favorite': bool(row['is_favorite']),
                    'is_trashed': bool(row['is_trashed']),
                    'created_at': row['created_at'],
                    'modified_at': row['modified_at'],
                })

        return entries
    
    def get_password(self, entry_id: int) -> Optional[str]:
        """Belirli bir entry'nin şifresini çözer ve döner."""
        if self.crypto is None:
            raise RuntimeError("Vault kilidi açık değil!")
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT encrypted_password, nonce FROM password_entries WHERE id = ?",
                (entry_id,)
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self.crypto.decrypt(row['encrypted_password'], row['nonce'])

    def toggle_favorite(self, entry_id: int) -> bool:
        """Favori durumunu tersine çevirir."""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT is_favorite FROM password_entries WHERE id = ?", (entry_id,))
            row = cursor.fetchone()
            if row is None:
                return False
            new_val = 0 if row['is_favorite'] else 1
            cursor.execute("UPDATE password_entries SET is_favorite = ? WHERE id = ?", (new_val, entry_id))
            self.conn.commit()
        return bool(new_val)

    def trash_password(self, entry_id: int) -> bool:
        """Şifreyi çöp kutusuna taşır."""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("UPDATE password_entries SET is_trashed = 1, modified_at = ? WHERE id = ?",
                           (datetime.utcnow().isoformat() + 'Z', entry_id))
            self.conn.commit()
        return cursor.rowcount > 0

    def restore_password(self, entry_id: int) -> bool:
        """Şifreyi çöp kutusundan geri yükler."""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("UPDATE password_entries SET is_trashed = 0, modified_at = ? WHERE id = ?",
                           (datetime.utcnow().isoformat() + 'Z', entry_id))
            self.conn.commit()
        return cursor.rowcount > 0

    def update_password(self, entry_id: int, title: str = None, username: str = None,
                       password: str = None, url: str = None, notes: str = None) -> bool:
        """
        Mevcut şifre girişini günceller.
        
        Args:
            entry_id: Güncellenecek entry ID
            Diğer parametreler: None verilirse değişmez
        
        Returns:
            True ise başarılı
        """
        if self.crypto is None:
            raise RuntimeError("Vault kilidi açık değil!")
        
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM password_entries WHERE id = ?", (entry_id,))
            row = cursor.fetchone()
            if row is None:
                return False
            new_title    = title    if title    is not None else row['title']
            new_username = username if username is not None else row['username']
            new_url      = url      if url      is not None else row['url']
            new_notes    = notes    if notes    is not None else row['notes']
            if password is not None:
                encrypted_password, nonce = self.crypto.encrypt(password)
            else:
                encrypted_password = row['encrypted_password']
                nonce = row['nonce']
            cursor.execute("""
                UPDATE password_entries
                SET title = ?, username = ?, encrypted_password = ?, nonce = ?,
                    url = ?, notes = ?, modified_at = ?
                WHERE id = ?
            """, (new_title, new_username, encrypted_password, nonce, new_url, new_notes,
                  datetime.utcnow().isoformat() + 'Z', entry_id))
            self.conn.commit()
        return True

    def delete_password(self, entry_id: int) -> bool:
        """Şifre girişini kalıcı olarak siler ve UUID'yi tombstone'a kaydeder."""
        with self._lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT uuid FROM password_entries WHERE id = ?", (entry_id,))
            row = cursor.fetchone()
            if row and row['uuid']:
                cursor.execute(
                    "INSERT OR IGNORE INTO deleted_uuids (uuid, deleted_at) VALUES (?, ?)",
                    (row['uuid'], datetime.utcnow().isoformat() + 'Z')
                )
            cursor.execute("DELETE FROM password_entries WHERE id = ?", (entry_id,))
            self.conn.commit()
        return cursor.rowcount > 0 if row else False
    
    def sync_with_mobile(self, mobile_passwords: list,
                         mobile_deleted_uuids: list = None) -> dict:
        """
        Mobil şifrelerle birleştir (UUID bazlı, last-modified-wins).
        Tüm entryleri (şifre metinleriyle) döndürür.
        """
        if self.crypto is None:
            raise RuntimeError("Vault kilidi açık değil!")

        if mobile_deleted_uuids is None:
            mobile_deleted_uuids = []

        with self._lock:
            cursor = self.conn.cursor()
            now = datetime.utcnow().isoformat() + 'Z'

            # 1. Mobile'ın sildiği kayıtları desktop'tan da sil
            for uuid_val in mobile_deleted_uuids:
                cursor.execute("DELETE FROM password_entries WHERE uuid = ?", (uuid_val,))
                # Tombstone'u da kaldır (artık senkronize edildi)
                cursor.execute("DELETE FROM deleted_uuids WHERE uuid = ?", (uuid_val,))

            # 2. Desktop'ın sildiği kayıtların listesini al (mobile'a göndermek için)
            cursor.execute("SELECT uuid FROM deleted_uuids")
            desktop_deleted = [r['uuid'] for r in cursor.fetchall()]
            desktop_deleted_set = set(desktop_deleted)

            for mp in mobile_passwords:
                uuid_val = mp.get('uuid', '')
                if not uuid_val:
                    continue
                # Desktop kalıcı silmişse mobilden gelen kopyayı yok say
                if uuid_val in desktop_deleted_set:
                    continue
                cursor.execute(
                    "SELECT id, modified_at FROM password_entries WHERE uuid = ?",
                    (uuid_val,)
                )
                existing = cursor.fetchone()
                is_fav     = 1 if mp.get('is_favorite') else 0
                is_trashed = 1 if mp.get('is_trashed')  else 0
                mob_mod    = mp.get('modified_at', now)
                if existing is None:
                    enc_pwd, nonce = self.crypto.encrypt(mp.get('password', ''))
                    cursor.execute("""
                        INSERT INTO password_entries
                        (uuid, title, username, encrypted_password, nonce, url, notes,
                         is_favorite, is_trashed, created_at, modified_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (uuid_val, mp['title'], mp.get('username', ''),
                          enc_pwd, nonce, mp.get('url', ''), mp.get('notes', ''),
                          is_fav, is_trashed,
                          mp.get('created_at', now), mob_mod))
                else:
                    local_mod = existing['modified_at'] or ''
                    if mob_mod > local_mod:
                        enc_pwd, nonce = self.crypto.encrypt(mp.get('password', ''))
                        cursor.execute("""
                            UPDATE password_entries
                            SET title=?, username=?, encrypted_password=?, nonce=?,
                                url=?, notes=?, is_favorite=?, is_trashed=?, modified_at=?
                            WHERE uuid=?
                        """, (mp['title'], mp.get('username', ''), enc_pwd, nonce,
                              mp.get('url', ''), mp.get('notes', ''),
                              is_fav, is_trashed, mob_mod, uuid_val))
            # 3. 30 günden eski tombstone'ları temizle (retention politikası)
            cutoff = (datetime.utcnow() - timedelta(days=30)).isoformat() + 'Z'
            cursor.execute("DELETE FROM deleted_uuids WHERE deleted_at < ?", (cutoff,))
            self.conn.commit()

            # 4. Tüm entryleri şifre metinleriyle döndür
            cursor.execute("""
                SELECT id, uuid, title, username, encrypted_password, nonce,
                       url, notes, is_favorite, is_trashed, created_at, modified_at
                FROM password_entries
            """)
            passwords = []
            for row in cursor.fetchall():
                try:
                    pwd_text = self.crypto.decrypt(row['encrypted_password'], row['nonce'])
                except Exception:
                    pwd_text = ''
                passwords.append({
                    'uuid':        row['uuid'] or '',
                    'title':       row['title'],
                    'username':    row['username'] or '',
                    'password':    pwd_text,
                    'url':         row['url']   or '',
                    'notes':       row['notes'] or '',
                    'is_favorite': bool(row['is_favorite']),
                    'is_trashed':  bool(row['is_trashed']),
                    'created_at':  row['created_at'],
                    'modified_at': row['modified_at'],
                })
            return {'passwords': passwords, 'deleted_uuids': desktop_deleted}

    def search_passwords(self, query: str) -> List[Dict]:
        """
        Başlık, kullanıcı adı veya URL'de arama yapar.
        
        Args:
            query: Arama terimi
        
        Returns:
            Eşleşen entry listesi
        """
        if self.crypto is None:
            raise RuntimeError("Vault kilidi açık değil!")

        with self._lock:
            cursor = self.conn.cursor()
            search_pattern = f"%{query}%"
            cursor.execute("""
                SELECT id, title, username, url, notes, created_at, modified_at
                FROM password_entries
                WHERE (title LIKE ? OR username LIKE ? OR url LIKE ?)
                  AND is_trashed = 0
                ORDER BY title ASC
            """, (search_pattern, search_pattern, search_pattern))

            entries = []
            for row in cursor.fetchall():
                entries.append({
                    'id': row['id'],
                    'title': row['title'],
                    'username': row['username'],
                    'url': row['url'],
                    'notes': row['notes'],
                    'created_at': row['created_at'],
                    'modified_at': row['modified_at']
                })

        return entries
    
    # Device Pairing İşlemleri
    
    def add_device_pair(self, device_name: str, shared_secret: bytes) -> int:
        """
        Mobil cihaz eşleşmesi ekler.
        Shared secret AES-256-GCM ile şifrelenerek saklanır.

        Args:
            device_name: Cihaz adı (örn: "iPhone 12")
            shared_secret: 32-byte shared secret

        Returns:
            Pair ID
        """
        if self.crypto is None:
            raise RuntimeError("Vault kilidi açık değil!")

        # shared_secret'i şifrele; format: nonce (12 byte) || ciphertext
        encrypted, nonce = self.crypto.encrypt(base64.b64encode(shared_secret).decode('ascii'))
        stored = nonce + encrypted

        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO device_pairs (device_name, shared_secret, paired_at)
            VALUES (?, ?, ?)
        """, (device_name, stored, datetime.utcnow().isoformat() + 'Z'))

        self.conn.commit()
        return cursor.lastrowid
    
    def get_device_pairs(self) -> List[Dict]:
        """
        Eşleşmiş cihazları listeler.
        
        Returns:
            [{id, device_name, paired_at, last_used}]
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, device_name, paired_at, last_used FROM device_pairs")
        
        pairs = []
        for row in cursor.fetchall():
            pairs.append({
                'id': row['id'],
                'device_name': row['device_name'],
                'paired_at': row['paired_at'],
                'last_used': row['last_used']
            })
        
        return pairs
    
    def get_shared_secret(self, pair_id: int) -> Optional[bytes]:
        """
        Belirli bir cihaz eşleşmesinin shared secret'ını çözerek döner.

        Geriye dönük uyumluluk (migration):
        - Eski format: 32 byte düz veri → otomatik şifrelenir ve güncellenir.
        - Yeni format: nonce (12 byte) || ciphertext

        Args:
            pair_id: Device pair ID

        Returns:
            Çözülmüş shared secret (bytes) veya None
        """
        if self.crypto is None:
            raise RuntimeError("Vault kilidi açık değil!")

        cursor = self.conn.cursor()
        cursor.execute("SELECT shared_secret FROM device_pairs WHERE id = ?", (pair_id,))
        row = cursor.fetchone()

        if row is None:
            return None

        stored = bytes(row['shared_secret'])

        # Migration: eski format tam olarak 32 byte düz veridir
        if len(stored) == 32:
            encrypted, nonce = self.crypto.encrypt(base64.b64encode(stored).decode('ascii'))
            new_stored = nonce + encrypted
            cursor.execute(
                "UPDATE device_pairs SET shared_secret = ? WHERE id = ?",
                (new_stored, pair_id)
            )
            self.conn.commit()
            return stored

        # Yeni format: ilk 12 byte nonce, geri kalan ciphertext
        nonce = stored[:12]
        ciphertext = stored[12:]
        secret_b64 = self.crypto.decrypt(ciphertext, nonce)
        return base64.b64decode(secret_b64)
    
    def update_device_last_used(self, pair_id: int):
        """Cihazın son kullanım zamanını günceller."""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE device_pairs SET last_used = ? WHERE id = ?
        """, (datetime.utcnow().isoformat() + 'Z', pair_id))
        self.conn.commit()
    
    def delete_device_pair(self, pair_id: int) -> bool:
        """Cihaz eşleşmesini siler."""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM device_pairs WHERE id = ?", (pair_id,))
        self.conn.commit()
        return cursor.rowcount > 0
    
    def close(self):
        """Veritabanı bağlantısını kapatır."""
        if self.conn:
            self.conn.close()
            self.conn = None
            self.crypto = None


# Test fonksiyonları
if __name__ == "__main__":
    import tempfile
    
    print("=== Vault Storage Test ===\n")
    
    # Geçici veritabanı kullan
    temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
    temp_db.close()
    
    vault = VaultStorage(temp_db.name)
    
    # 1. Vault başlatma
    print("1. Vault Başlatma:")
    master_password = "MyMasterPassword123!"
    vault.initialize_vault(master_password)
    print(f"   Vault oluşturuldu ✓\n")
    
    # 2. Vault kilidini açma
    print("2. Vault Unlock:")
    success = vault.unlock_vault(master_password)
    print(f"   Doğru parola: {success} ✓")
    
    wrong_success = vault.unlock_vault("WrongPassword")
    print(f"   Yanlış parola: {not wrong_success} ✓\n")
    
    # Doğru parola ile tekrar aç
    vault.unlock_vault(master_password)
    
    # 3. Şifre ekleme
    print("3. Şifre Ekleme:")
    id1 = vault.add_password("Gmail", "user@gmail.com", "GmailPass123", "https://gmail.com")
    id2 = vault.add_password("Facebook", "user@fb.com", "FbPass456", "https://facebook.com")
    id3 = vault.add_password("GitHub", "developer", "GithubToken789", "https://github.com", "Personal access token")
    print(f"   3 şifre eklendi (IDs: {id1}, {id2}, {id3}) ✓\n")
    
    # 4. Şifreleri listeleme
    print("4. Tüm Şifreler:")
    entries = vault.get_all_passwords()
    for entry in entries:
        print(f"   - {entry['title']}: {entry['username']}")
    print()

    # 5. Şifre okuma
    print("5. Şifre Okuma:")
    password = vault.get_password(id1)
    print(f"   Gmail sifresi: {password}")
    print()

    # 6. Şifre arama
    print("6. Şifre Arama:")
    results = vault.search_passwords("git")
    print(f"   'git' aramasi: {len(results)} sonuc")
    for result in results:
        print(f"   - {result['title']}")
    print()

    # 7. Şifre guncelleme
    print("7. Şifre Guncelleme:")
    vault.update_password(id1, password="NewGmailPass999")
    new_password = vault.get_password(id1)
    print(f"   Gmail yeni sifre: {new_password}")
    print()

    # 8. Device pairing (sifreli)
    print("8. Device Pairing (sifreli):")
    secret = os.urandom(32)
    pair_id = vault.add_device_pair("Test Phone", secret)
    recovered = vault.get_shared_secret(pair_id)
    print(f"   Secret eslesiyor: {secret == recovered}")
    pairs = vault.get_device_pairs()
    print(f"   Eslesmiş cihazlar: {len(pairs)}")
    print()

    # 9. Şifre silme
    print("9. Şifre Silme:")
    vault.delete_password(id2)
    remaining = vault.get_all_passwords()
    print(f"   Facebook silindi, kalan: {len(remaining)} sifre")
    print()

    vault.close()
    os.unlink(temp_db.name)

    print("=== Tum Testler Basarili ===")
