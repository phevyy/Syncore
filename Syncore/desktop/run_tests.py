"""
Test Suite Runner - Tüm modüllerin testlerini çalıştırır
"""

import sys
import os

# Desktop modüllerini PATH'e ekle
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def run_all_tests():
    """Tüm test modüllerini sırayla çalıştırır."""
    
    print("=" * 70)
    print("PASSWORD VAULT - KAPSAMLI TEST SÜİTİ")
    print("=" * 70)
    print()
    
    tests = [
        ("Kriptografi Modülü (crypto_manager.py)", "crypto_manager"),
        ("Vault Storage (vault_storage.py)", "vault_storage"),
        ("Network Server/Client (network_server.py)", "network_server"),
    ]
    
    results = []
    
    for test_name, module_name in tests:
        print(f"\n{'=' * 70}")
        print(f"▶️  TEST: {test_name}")
        print(f"{'=' * 70}\n")
        
        try:
            # Modülü import et ve çalıştır (if __name__ == "__main__" bloğu çalışır)
            module = __import__(module_name)
            
            # Test kodu çalıştır
            if hasattr(module, '__file__'):
                exec(open(module.__file__).read())
            
            results.append((test_name, True, None))
        except Exception as e:
            print(f"\n❌ TEST BAŞARISIZ: {e}")
            results.append((test_name, False, str(e)))
    
    # Özet
    print(f"\n\n{'=' * 70}")
    print("TEST ÖZETİ")
    print(f"{'=' * 70}\n")
    
    passed = sum(1 for _, success, _ in results if success)
    failed = sum(1 for _, success, _ in results if not success)
    
    for test_name, success, error in results:
        status = "✅ BAŞARILI" if success else f"❌ BAŞARISIZ: {error}"
        print(f"  {test_name}: {status}")
    
    print(f"\nToplam: {len(results)} test")
    print(f"Başarılı: {passed}")
    print(f"Başarısız: {failed}")
    
    if failed == 0:
        print("\n🎉 TÜM TESTLER BAŞARILI! 🎉")
    else:
        print(f"\n⚠️  {failed} TEST BAŞARISIZ")
    
    print(f"{'=' * 70}\n")

if __name__ == "__main__":
    run_all_tests()
