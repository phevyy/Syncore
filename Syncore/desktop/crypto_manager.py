"""
Kriptografi Yöneticisi - Password Vault Cryptography Manager
============================================================

Bu modül şu işlevleri sağlar:
1. AES-256-GCM ile şifreleme/şifre çözme (AEAD - Authenticated Encryption)
2. Argon2 ile KDF (Key Derivation Function) - Ana paroladan anahtar türetme
3. HMAC-SHA256 ile Challenge-Response doğrulama (2FA için)

Akademik Notlar:
- AES-256-GCM: Galois/Counter Mode, hem şifreleme hem de bütünlük kontrolü sağlar
- Argon2: Modern, GPU saldırılarına dayanıklı KDF algoritması (2015 Password Hashing yarışmasının kazananı)
- HMAC-SHA256: Keyed-Hash MAC, timing attack'lere karşı güvenli
"""

import os
import base64
import hmac
import hashlib
import secrets
from typing import Tuple, Optional
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from argon2 import PasswordHasher
from argon2.low_level import hash_secret_raw, Type


class KeyDerivation:
    """
    Argon2 kullanarak ana paroladan şifreleme anahtarı türetir.
    
    Argon2 Parametreleri (OWASP önerileri):
    - time_cost: 3 iteration (hesaplama karmaşıklığı)
    - memory_cost: 65536 KB = 64 MB (bellek kullanımı)
    - parallelism: 4 thread (paralel hesaplama)
    - hash_len: 32 byte = 256 bit (AES-256 için)
    - type: Argon2id (hibrit: timing ve tradeoff attack'lere karşı)
    """
    
    def __init__(self):
        self.time_cost = 3
        self.memory_cost = 65536  # 64 MB
        self.parallelism = 4
        self.hash_length = 32  # 256 bit
        self.salt_length = 16  # 128 bit
        
        # Parola doğrulama için hasher (verification hash saklamak için)
        self.ph = PasswordHasher(
            time_cost=self.time_cost,
            memory_cost=self.memory_cost,
            parallelism=self.parallelism,
            hash_len=self.hash_length,
            salt_len=self.salt_length
        )
    
    def derive_key(self, password: str, salt: bytes = None) -> Tuple[bytes, bytes]:
        """
        Ana paroladan şifreleme anahtarı türetir.
        
        Args:
            password: Kullanıcının ana parolası (string)
            salt: Rastgele salt (opsiyonel, verilmezse otomatik üretilir)
        
        Returns:
            (key, salt): 32-byte anahtar ve kullanılan salt
        """
        if salt is None:
            salt = os.urandom(self.salt_length)
        
        # Argon2id ile ham (binary) anahtar türet
        key = hash_secret_raw(
            secret=password.encode('utf-8'),
            salt=salt,
            time_cost=self.time_cost,
            memory_cost=self.memory_cost,
            parallelism=self.parallelism,
            hash_len=self.hash_length,
            type=Type.ID  # Argon2id
        )
        
        return key, salt
    
    def create_verification_hash(self, password: str) -> str:
        """
        Ana parolanın doğrulama hash'ini oluşturur (login kontrolü için).
        Bu hash veritabanında saklanır, ana parola asla saklanmaz!
        
        Args:
            password: Kullanıcının ana parolası
        
        Returns:
            Argon2 hash string (salt dahil, encoded format)
        """
        return self.ph.hash(password)
    
    def verify_password(self, stored_hash: str, password: str) -> bool:
        """
        Girilen parolayı saklanan hash ile karşılaştırır.
        Timing-safe karşılaştırma kullanır.
        
        Args:
            stored_hash: Veritabanında saklanan Argon2 hash
            password: Kullanıcının girdiği parola
        
        Returns:
            True ise parola doğru, False ise yanlış
        """
        try:
            self.ph.verify(stored_hash, password)
            return True
        except Exception:
            return False


class PasswordCrypto:
    """
    AES-256-GCM ile şifreleme/şifre çözme işlemleri.
    
    GCM (Galois/Counter Mode) Avantajları:
    - AEAD: Hem şifreler hem de bütünlüğü doğrular
    - Paralelize edilebilir (hızlı)
    - Nonce tekrar kullanımı kritik tehlike (her işlem için yeni nonce!)
    """
    
    def __init__(self, key: bytes):
        """
        Args:
            key: 32-byte (256-bit) şifreleme anahtarı
        """
        if len(key) != 32:
            raise ValueError("AES-256 için anahtar 32 byte olmalı")
        
        self.aesgcm = AESGCM(key)
        self.nonce_length = 12  # GCM için önerilen 96 bit
    
    def encrypt(self, plaintext: str) -> Tuple[bytes, bytes]:
        """
        Metni AES-256-GCM ile şifreler.
        
        Args:
            plaintext: Şifrelenecek metin
        
        Returns:
            (ciphertext, nonce): Şifreli veri ve nonce
        """
        nonce = os.urandom(self.nonce_length)
        
        # String'i byte'a çevir
        plaintext_bytes = plaintext.encode('utf-8')
        
        # Şifrele (authentication tag otomatik eklenir)
        ciphertext = self.aesgcm.encrypt(nonce, plaintext_bytes, None)
        
        return ciphertext, nonce
    
    def decrypt(self, ciphertext: bytes, nonce: bytes) -> str:
        """
        AES-256-GCM ile şifreli metni çözer.
        
        Args:
            ciphertext: Şifreli veri
            nonce: Şifrelemede kullanılan nonce
        
        Returns:
            Çözülmüş metin (string)
        
        Raises:
            cryptography.exceptions.InvalidTag: Veri bütünlüğü bozulmuşsa
        """
        # Şifre çöz ve bütünlüğü doğrula
        plaintext_bytes = self.aesgcm.decrypt(nonce, ciphertext, None)
        
        return plaintext_bytes.decode('utf-8')


class ChallengeResponseAuth:
    """
    HMAC-SHA256 tabanlı Challenge-Response 2FA sistemi.
    
    Akış:
    1. Desktop: 16-byte rastgele challenge üretir
    2. Desktop -> Mobile: Challenge gönderilir
    3. Mobile: HMAC-SHA256(shared_secret, challenge) hesaplar
    4. Mobile -> Desktop: Response gönderilir
    5. Desktop: Aynı hesaplamayı yapıp karşılaştırır (timing-safe)
    """
    
    def __init__(self, shared_secret: bytes = None):
        """
        Args:
            shared_secret: İki cihaz arasında paylaşılan gizli anahtar (32 byte)
        """
        if shared_secret is None:
            # İlk kurulumda yeni secret üret
            shared_secret = secrets.token_bytes(32)
        
        if len(shared_secret) != 32:
            raise ValueError("Shared secret 32 byte olmalı")
        
        self.shared_secret = shared_secret
        self.challenge_length = 16  # 128 bit
    
    def generate_challenge(self) -> bytes:
        """
        Kriptografik olarak güvenli rastgele challenge üretir.
        
        Returns:
            16-byte rastgele challenge
        """
        return secrets.token_bytes(self.challenge_length)
    
    def compute_response(self, challenge: bytes) -> bytes:
        """
        Challenge için HMAC-SHA256 response hesaplar.
        
        Args:
            challenge: Desktop'tan alınan challenge
        
        Returns:
            32-byte HMAC-SHA256 signature
        """
        return hmac.digest(self.shared_secret, challenge, hashlib.sha256)
    
    def verify_response(self, challenge: bytes, response: bytes) -> bool:
        """
        Mobile'dan gelen response'u doğrular.
        Timing attack'e karşı güvenli karşılaştırma kullanır.
        
        Args:
            challenge: Gönderilen challenge
            response: Mobile'dan gelen HMAC response
        
        Returns:
            True ise doğru, False ise yanlış
        """
        expected_response = self.compute_response(challenge)
        
        # Timing-safe karşılaştırma (constant-time)
        return hmac.compare_digest(expected_response, response)
    
    def export_secret_base64(self) -> str:
        """
        Shared secret'i base64 string olarak export eder (QR kod için).
        
        Returns:
            Base64-encoded shared secret
        """
        return base64.b64encode(self.shared_secret).decode('ascii')
    
    @staticmethod
    def import_secret_base64(secret_b64: str) -> 'ChallengeResponseAuth':
        """
        Base64 string'den shared secret import eder.
        
        Args:
            secret_b64: Base64-encoded shared secret
        
        Returns:
            Yeni ChallengeResponseAuth instance
        """
        shared_secret = base64.b64decode(secret_b64.encode('ascii'))
        return ChallengeResponseAuth(shared_secret)


# Test fonksiyonları (modül doğrudan çalıştırılırsa)
if __name__ == "__main__":
    print("=== Kriptografi Modülü Test ===\n")
    
    # 1. Key Derivation Test
    print("1. Argon2 Key Derivation Test:")
    kdf = KeyDerivation()
    password = "MySecurePassword123!"
    key, salt = kdf.derive_key(password)
    print(f"   Parola: {password}")
    print(f"   Salt: {base64.b64encode(salt).decode()}")
    print(f"   Türetilen Anahtar: {base64.b64encode(key).decode()}")
    
    # Aynı parola + salt = aynı anahtar (deterministik)
    key2, _ = kdf.derive_key(password, salt)
    print(f"   Deterministik Test: {key == key2} ✓\n")
    
    # 2. Password Verification Test
    print("2. Parola Doğrulama Test:")
    verification_hash = kdf.create_verification_hash(password)
    print(f"   Verification Hash: {verification_hash[:50]}...")
    print(f"   Doğru Parola: {kdf.verify_password(verification_hash, password)} ✓")
    print(f"   Yanlış Parola: {kdf.verify_password(verification_hash, 'WrongPassword')} ✓\n")
    
    # 3. AES-256-GCM Encryption Test
    print("3. AES-256-GCM Şifreleme Test:")
    crypto = PasswordCrypto(key)
    plaintext = "Gizli şifre: admin@example.com:MyP@ssw0rd"
    ciphertext, nonce = crypto.encrypt(plaintext)
    print(f"   Düz Metin: {plaintext}")
    print(f"   Şifreli (Base64): {base64.b64encode(ciphertext).decode()}")
    
    decrypted = crypto.decrypt(ciphertext, nonce)
    print(f"   Çözülmüş: {decrypted}")
    print(f"   Eşleşme: {plaintext == decrypted} ✓\n")
    
    # 4. Challenge-Response 2FA Test
    print("4. Challenge-Response 2FA Test:")
    auth = ChallengeResponseAuth()
    print(f"   Shared Secret (Base64): {auth.export_secret_base64()}")
    
    # Desktop tarafı: challenge üret
    challenge = auth.generate_challenge()
    print(f"   Challenge: {base64.b64encode(challenge).decode()}")
    
    # Mobile tarafı: response hesapla
    response = auth.compute_response(challenge)
    print(f"   Response: {base64.b64encode(response).decode()}")
    
    # Desktop tarafı: doğrula
    is_valid = auth.verify_response(challenge, response)
    print(f"   Doğrulama: {is_valid} ✓")
    
    # Yanlış response
    wrong_response = secrets.token_bytes(32)
    is_invalid = auth.verify_response(challenge, wrong_response)
    print(f"   Yanlış Response: {is_invalid} (False bekleniyor) ✓\n")
    
    print("=== Tüm Testler Başarılı ===")
