# -*- coding: utf-8 -*-
"""
Hızlı Test Scripti - Tüm modüllerin çalışıp çalışmadığını test eder
"""

import sys
import os

# Encoding ayarla
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

def test_crypto():
    """Kriptografi modülünü test et"""
    print("\n" + "="*60)
    print("TEST 1/3: Kriptografi Modülü")
    print("="*60)
    
    try:
        from crypto_manager import PasswordCrypto, KeyDerivation, ChallengeResponseAuth
        
        # Key Derivation
        kdf = KeyDerivation()
        key, salt = kdf.derive_key("TestPassword123!")
        print("[OK] Key Derivation - Argon2")
        
        # Şifreleme
        crypto = PasswordCrypto(key)
        ciphertext, nonce = crypto.encrypt("Gizli mesaj: admin@test.com:Pass123")
        plaintext = crypto.decrypt(ciphertext, nonce)
        assert plaintext == "Gizli mesaj: admin@test.com:Pass123"
        print("[OK] AES-256-GCM Şifreleme")
        
        # Challenge-Response
        cr = ChallengeResponseAuth(b"shared_secret_key_32bytes_long!!")
        challenge = cr.generate_challenge()
        response = cr.compute_response(challenge)
        is_valid = cr.verify_response(challenge, response)
        assert is_valid
        print("[OK] HMAC-SHA256 Challenge-Response")
        
        print("\n✓ Kriptografi Testi BAŞARILI\n")
        return True
    except Exception as e:
        print(f"\n✗ Kriptografi Testi BAŞARISIZ: {e}\n")
        return False

def test_vault_storage():
    """Vault storage modülünü test et"""
    print("="*60)
    print("TEST 2/3: Vault Storage (SQLite)")
    print("="*60)
    
    try:
        from vault_storage import VaultStorage
        import os
        
        # Test veritabanı
        db_path = "test_vault.db"
        if os.path.exists(db_path):
            os.remove(db_path)
        
        # Vault oluştur
        vault = VaultStorage(db_path)
        vault.initialize_vault("TestMasterPassword123!")
        print("[OK] Vault Oluşturuldu")
        
        # Vault aç
        vault.unlock_vault("TestMasterPassword123!")
        print("[OK] Vault Açıldı")
        
        # Şifre ekle
        entry_id = vault.add_password(
            title="Test Gmail",
            username="test@gmail.com",
            password="SuperSecret456",
            url="https://gmail.com"
        )
        print("[OK] Şifre Eklendi")
        
        # Şifre oku
        password = vault.get_password(entry_id)
        assert password == "SuperSecret456"
        print("[OK] Şifre Okundu")
        
        # Şifre sil
        vault.delete_password(entry_id)
        entries = vault.get_all_passwords()
        assert len(entries) == 0
        print("[OK] Şifre Silindi")
        
        vault.close()
        os.remove(db_path)
        
        print("\n✓ Vault Storage Testi BAŞARILI\n")
        return True
    except Exception as e:
        print(f"\n✗ Vault Storage Testi BAŞARISIZ: {e}\n")
        return False

def test_network():
    """Network modülünü test et"""
    print("="*60)
    print("TEST 3/3: Network Server/Client (TCP)")
    print("="*60)
    
    try:
        from network_server import NetworkServer, NetworkClient
        import base64
        import secrets
        import time
        
        # Server başlat
        server = NetworkServer()
        server.start()
        server_ip = server.get_server_ip()
        print(f"[OK] Server Başlatıldı: {server_ip}")
        
        time.sleep(0.5)  # Server hazır olsun
        
        # Client ile ping
        client = NetworkClient("127.0.0.1", 8765)
        pong = client.send_ping()
        assert pong["type"] == "pong"
        print(f"[OK] Ping/Pong: {pong['server_name']}")
        
        # Challenge-Response
        shared_secret = secrets.token_bytes(32)
        success_result = {"value": None}
        
        def callback(success, device_id):
            success_result["value"] = success
        
        challenge_b64 = server.send_challenge(shared_secret, callback)
        print(f"[OK] Challenge Gönderildi: {challenge_b64[:32]}...")
        
        # Client response gönder
        response = client.send_response(challenge_b64, shared_secret, 1)
        assert response["type"] == "success"
        print("[OK] Response Doğrulandı")
        
        time.sleep(0.5)  # Callback çalışsın
        assert success_result["value"] == True
        print("[OK] Callback Tetiklendi")
        
        server.stop()
        
        print("\n✓ Network Testi BAŞARILI\n")
        return True
    except Exception as e:
        print(f"\n✗ Network Testi BAŞARISIZ: {e}\n")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("\n" + "="*60)
    print("PASSWORD VAULT 2FA - HIZLI TEST SÜİTİ")
    print("="*60)
    
    results = []
    results.append(("Kriptografi", test_crypto()))
    results.append(("Vault Storage", test_vault_storage()))
    results.append(("Network", test_network()))
    
    # Özet
    print("="*60)
    print("TEST ÖZETİ")
    print("="*60)
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    for name, success in results:
        status = "✓ BAŞARILI" if success else "✗ BAŞARISIZ"
        print(f"  {name}: {status}")
    
    print(f"\nToplam: {total} test")
    print(f"Başarılı: {passed}/{total}")
    
    if passed == total:
        print("\n🎉 TÜM TESTLER BAŞARILI! 🎉\n")
        sys.exit(0)
    else:
        print(f"\n⚠ {total - passed} TEST BAŞARISIZ\n")
        sys.exit(1)
