"""
Network Server - Desktop TCP Server (Challenge-Response 2FA)
=============================================================

Masaüstü uygulaması için TCP sunucusu.
Yerel ağda mobil cihazlarla Challenge-Response iletişimi.

İletişim Protokolü (length-prefix framing + JSON):
  Her mesaj: [4-byte big-endian uzunluk] + [UTF-8 JSON gövde]

  1. Mobile -> Desktop: {"type": "auth_request", "device_id": <int>}
  2. Desktop -> Mobile: {"type": "challenge", "challenge": "<base64>"}
  3. Mobile -> Desktop: {"type": "response", "response": "<base64_hmac>", "device_id": <int>}
  4. Desktop -> Mobile: {"type": "success"|"error", "message": "<str>"}

Güvenlik özellikleri:
  - 30 saniye challenge timeout
  - Tek seferlik auth (replay koruması: auth_done flag + lock)
  - Rate limiting: aynı IP'den 60 saniyede max 5 deneme
  - Tüm mesajlar length-prefix ile çerçevelendi (kısmi okuma yok)
"""

import json
import socket
import struct
import base64
import threading
import time
from collections import defaultdict
from typing import Callable, Optional

from crypto_manager import ChallengeResponseAuth


# ── Framing helpers ───────────────────────────────────────────────────────

def _recv_exact(sock: socket.socket, n: int) -> bytes:
    """Tam olarak n byte okur; bağlantı kesilirse ConnectionError fırlatır."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Bağlantı beklenmedik şekilde kesildi")
        buf.extend(chunk)
    return bytes(buf)


def send_msg(sock: socket.socket, payload: dict) -> None:
    """Mesajı length-prefix (4-byte big-endian) + JSON olarak gönderir."""
    data = json.dumps(payload).encode('utf-8')
    sock.sendall(struct.pack('>I', len(data)) + data)


def recv_msg(sock: socket.socket) -> dict:
    """Length-prefix protokolüyle tam bir JSON mesajı okur."""
    raw_len = _recv_exact(sock, 4)
    msg_len = struct.unpack('>I', raw_len)[0]
    if msg_len > 65_536:
        raise ValueError(f"Mesaj çok büyük: {msg_len} byte")
    data = _recv_exact(sock, msg_len)
    return json.loads(data.decode('utf-8'))


# ── Server ────────────────────────────────────────────────────────────────

class NetworkServer:
    """
    TCP sunucusu — sadece QR akışını (auth_request → challenge → response) destekler.
    """

    CHALLENGE_TIMEOUT  = 30   # saniye: challenge gönderildikten response beklenecek süre
    RATE_LIMIT_WINDOW  = 60   # saniye: rate limit penceresi
    RATE_LIMIT_MAX     = 5    # pencere içinde aynı IP'den max bağlantı

    def __init__(self, host: str = "0.0.0.0", port: int = 8765):
        self.host = host
        self.port = port
        self.server_socket: Optional[socket.socket] = None
        self.is_running = False
        self.server_thread: Optional[threading.Thread] = None

        # QR auto-challenge state
        self._auto_shared_secret: Optional[bytes] = None
        self._auto_callback: Optional[Callable] = None
        self._auth: Optional[ChallengeResponseAuth] = None
        self._expected_username: Optional[str] = None

        # CRUD session state
        self._vault = None
        self._on_data_changed: Optional[Callable] = None
        self._data_changed_flag = False
        self._flag_lock = threading.Lock()

        # Replay koruması: ilk başarılı/başarısız auth sonrası yeni deneme reddedilir
        self._auth_done = False
        self._auth_lock = threading.Lock()

        # Rate limiting: {ip_str: [timestamp, ...]}
        self._rate: dict = defaultdict(list)
        self._rate_lock = threading.Lock()

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> None:
        """Sunucuyu background thread'de başlatır."""
        if self.is_running:
            return

        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
            self.is_running = True
            self.server_thread = threading.Thread(
                target=self._listen_loop, daemon=True
            )
            self.server_thread.start()
            print(f"[Server] TCP sunucusu başlatıldı: {self.host}:{self.port}")
        except OSError as e:
            print(f"[Server] Port {self.port} kullanımda: {e}")
            self.is_running = False

    def stop(self) -> None:
        """Sunucuyu durdurur."""
        self.is_running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass
            self.server_socket = None
        print("[Server] TCP sunucusu durduruldu")

    # ── Configuration ─────────────────────────────────────────────────────

    def set_vault(self, vault, on_data_changed: Optional[Callable] = None) -> None:
        """Auth sonrası CRUD session için vault'u ayarla."""
        self._vault = vault
        self._on_data_changed = on_data_changed

    def set_auto_challenge(self, shared_secret: Optional[bytes], callback: Callable,
                           expected_username: Optional[str] = None) -> None:
        """
        QR akışı için: mobil bağlandığında otomatik challenge gönder.

        shared_secret None olabilir (mobile-first / TOFU modu):
        bu durumda ilk bağlanan mobilin gönderdiği password_hash güvenilir kabul edilir.
        callback: callback(success, device_id, username, secret_b64)
        """
        self._auto_shared_secret = shared_secret
        self._auto_callback = callback
        self._auth = ChallengeResponseAuth(shared_secret) if shared_secret else None
        self._expected_username = expected_username
        self._auth_done = False
        print("[Server] QR auto-challenge modu aktif")

    # ── Rate limiting ─────────────────────────────────────────────────────

    def _is_rate_limited(self, ip: str) -> bool:
        """True dönerse bu IP çok fazla deneme yaptı, reddet."""
        now = time.time()
        with self._rate_lock:
            self._rate[ip] = [
                t for t in self._rate[ip]
                if now - t < self.RATE_LIMIT_WINDOW
            ]
            if len(self._rate[ip]) >= self.RATE_LIMIT_MAX:
                return True
            self._rate[ip].append(now)
            return False

    # ── Network loop ──────────────────────────────────────────────────────

    def _listen_loop(self) -> None:
        """Ana dinleme döngüsü (background thread)."""
        self.server_socket.settimeout(1.0)
        while self.is_running:
            try:
                client_socket, address = self.server_socket.accept()
                threading.Thread(
                    target=self._handle_client,
                    args=(client_socket, address),
                    daemon=True
                ).start()
            except socket.timeout:
                continue
            except Exception as e:
                if self.is_running:
                    print(f"[Server] Accept hatası: {e}")

    def _handle_client(self, client_socket: socket.socket, address: tuple) -> None:
        """Gelen bağlantıyı işler."""
        ip = address[0]
        print(f"[Server] Bağlantı: {ip}:{address[1]}")

        try:
            client_socket.settimeout(35.0)

            if self._is_rate_limited(ip):
                print(f"[Server] Rate limit aşıldı: {ip}")
                send_msg(client_socket, {
                    'type': 'error',
                    'message': 'Çok fazla deneme. Lütfen bekleyin.'
                })
                return

            message = recv_msg(client_socket)
            msg_type = message.get('type')

            if msg_type == 'auth_request':
                self._handle_auth_request(client_socket, message)
            elif msg_type == 'ping':
                send_msg(client_socket, {
                    'type': 'pong',
                    'server_name': 'Syncore Desktop',
                    'version': '2.0'
                })
            else:
                print(f"[Server] Bilinmeyen mesaj tipi: {msg_type}")

        except json.JSONDecodeError:
            print("[Server] Geçersiz JSON alındı")
        except ConnectionError as e:
            print(f"[Server] Bağlantı hatası: {e}")
        except Exception as e:
            print(f"[Server] Client işleme hatası: {e}")
        finally:
            client_socket.close()

    def _handle_auth_request(
        self, client_socket: socket.socket, message: dict
    ) -> None:
        """
        QR auth akışı: auth_request → challenge → response → success/error

        Replay koruması: _auth_done True ise ikinci deneme reddedilir.
        Timeout: challenge gönderildikten CHALLENGE_TIMEOUT saniye içinde
                 response gelmezse bağlantı reddedilir.
        """
        device_id = message.get('device_id', 0)
        req_username = message.get('username', '')

        with self._auth_lock:
            if self._auth_done:
                send_msg(client_socket, {'type': 'error',
                                         'message': 'Bu oturum zaten tamamlandı.'})
                return

            # TOFU: shared_secret yoksa mobilin gönderdiği password_hash'i kullan
            if not self._auto_shared_secret:
                provided_hash = message.get('password_hash', '')
                if not provided_hash:
                    send_msg(client_socket, {'type': 'error',
                                             'message': 'Kimlik bilgisi gerekli.'})
                    return
                try:
                    self._auto_shared_secret = base64.b64decode(provided_hash)
                    self._auth = ChallengeResponseAuth(self._auto_shared_secret)
                except Exception:
                    send_msg(client_socket, {'type': 'error',
                                             'message': 'Geçersiz kimlik bilgisi.'})
                    return

            if not self._auth:
                send_msg(client_socket, {'type': 'error',
                                         'message': 'Server henüz hazır değil.'})
                return

        # Kullanıcı adı kontrolü — farklı kullanıcıysa TOFU ile kabul et
        if self._expected_username and req_username != self._expected_username:
            provided_hash = message.get('password_hash', '')
            if provided_hash:
                try:
                    with self._auth_lock:
                        self._auto_shared_secret = base64.b64decode(provided_hash)
                        self._auth = ChallengeResponseAuth(self._auto_shared_secret)
                        self._expected_username = req_username
                    print(f"[Server] Farklı kullanıcı TOFU: {req_username!r}")
                except Exception:
                    send_msg(client_socket, {'type': 'error',
                                             'message': 'Geçersiz kimlik bilgisi.'})
                    return
            else:
                send_msg(client_socket, {'type': 'error',
                                         'message': 'Kullanıcı adı eşleşmiyor.'})
                print(f"[Server] Yanlış kullanıcı adı: {req_username!r}")
                return

        # Challenge üret ve gönder
        challenge = self._auth.generate_challenge()
        challenge_sent_at = time.time()

        send_msg(client_socket, {
            'type': 'challenge',
            'challenge': base64.b64encode(challenge).decode('ascii')
        })

        # Response bekle
        resp_msg = recv_msg(client_socket)

        # Timeout kontrolü
        elapsed = time.time() - challenge_sent_at
        if elapsed > self.CHALLENGE_TIMEOUT:
            send_msg(client_socket, {
                'type': 'error',
                'message': f'Challenge süresi doldu ({self.CHALLENGE_TIMEOUT}s).'
            })
            print(f"[Server] Challenge timeout ({elapsed:.1f}s)")
            return

        # Response doğrula
        response_b64 = resp_msg.get('response', '')
        try:
            response_bytes = base64.b64decode(response_b64)
        except Exception:
            send_msg(client_socket, {
                'type': 'error',
                'message': 'Geçersiz response formatı.'
            })
            return

        if self._auth.verify_response(challenge, response_bytes):
            # Başarılı: replay kilidini kapat (double-check with lock)
            with self._auth_lock:
                if self._auth_done:
                    send_msg(client_socket, {
                        'type': 'error',
                        'message': 'Eş zamanlı oturum: reddedildi.'
                    })
                    return
                self._auth_done = True

            print(f"[Server] 2FA başarılı — device_id={device_id}")
            send_msg(client_socket, {
                'type': 'success',
                'message': 'Doğrulama başarılı.'
            })
            secret_b64 = base64.b64encode(self._auto_shared_secret).decode()
            if self._auto_callback:
                self._auto_callback(True, device_id, req_username, secret_b64)
            # Vault varsa CRUD session'a geç (bağlantı açık kalır)
            if self._vault is not None:
                self._run_session(client_socket)
        else:
            print(f"[Server] 2FA başarısız — yanlış HMAC (device_id={device_id})")
            send_msg(client_socket, {
                'type': 'error',
                'message': 'Geçersiz response.'
            })
            if self._auto_callback:
                self._auto_callback(False, device_id, req_username, '')

    # ── CRUD Session ──────────────────────────────────────────────────────

    def _run_session(self, sock: socket.socket) -> None:
        """Auth sonrası CRUD döngüsü — bağlantı kapanana dek çalışır."""
        sock.settimeout(300.0)
        print("[Server] CRUD session başladı")
        try:
            while self.is_running:
                try:
                    msg  = recv_msg(sock)
                    resp = self._handle_crud(msg)
                    send_msg(sock, resp)
                    if msg.get('type') == 'close':
                        break
                except (ConnectionError, TimeoutError, OSError):
                    break
                except Exception as e:
                    try:
                        send_msg(sock, {'type': 'error', 'message': str(e)})
                    except Exception:
                        break
        finally:
            # Session bitti — yeni QR bağlantısına izin ver
            with self._auth_lock:
                self._auth_done = False
            print("[Server] CRUD session bitti, yeni bağlantıya hazır")

    def _handle_crud(self, msg: dict) -> dict:
        """CRUD isteğini işler ve yanıt döner."""
        vault = self._vault
        if vault is None:
            return {'type': 'error', 'message': 'Vault hazır değil.'}

        t = msg.get('type', '')
        try:
            if t == 'list_passwords':
                entries = vault.get_all_passwords(
                    favorites_only=msg.get('favorites_only', False),
                    trashed_only=msg.get('trashed_only', False),
                )
                return {'type': 'passwords_list', 'entries': entries}

            elif t == 'get_password':
                pwd = vault.get_password(int(msg['id']))
                return {'type': 'password_data', 'id': msg['id'], 'password': pwd or ''}

            elif t == 'add_password':
                new_id = vault.add_password(
                    title    = msg['title'],
                    username = msg.get('username', ''),
                    password = msg['password'],
                    url      = msg.get('url', ''),
                    notes    = msg.get('notes', ''),
                    uuid     = msg.get('uuid'),
                )
                self._notify_change()
                return {'type': 'success', 'id': new_id}

            elif t == 'update_password':
                vault.update_password(
                    int(msg['id']),
                    title    = msg.get('title'),
                    username = msg.get('username'),
                    password = msg.get('password'),
                    url      = msg.get('url'),
                    notes    = msg.get('notes'),
                )
                self._notify_change()
                return {'type': 'success'}

            elif t == 'trash_password':
                vault.trash_password(int(msg['id']))
                self._notify_change()
                return {'type': 'success'}

            elif t == 'restore_password':
                vault.restore_password(int(msg['id']))
                self._notify_change()
                return {'type': 'success'}

            elif t == 'delete_password':
                vault.delete_password(int(msg['id']))
                self._notify_change()
                return {'type': 'success'}

            elif t == 'toggle_favorite':
                vault.toggle_favorite(int(msg['id']))
                self._notify_change()
                return {'type': 'success'}

            elif t == 'sync':
                mobile_passwords     = msg.get('passwords', [])
                mobile_deleted_uuids = msg.get('deleted_uuids', [])
                result = vault.sync_with_mobile(mobile_passwords, mobile_deleted_uuids)
                self._notify_change()
                return {
                    'type':         'sync_response',
                    'passwords':    result['passwords'],
                    'deleted_uuids': result['deleted_uuids'],
                }

            elif t == 'poll_events':
                with self._flag_lock:
                    changed = self._data_changed_flag
                    self._data_changed_flag = False
                return {'type': 'events', 'data_changed': changed}

            elif t == 'close':
                return {'type': 'bye'}

            else:
                return {'type': 'error', 'message': f'Bilinmeyen istek: {t}'}

        except KeyError as e:
            return {'type': 'error', 'message': f'Eksik alan: {e}'}
        except Exception as e:
            return {'type': 'error', 'message': str(e)}

    def mark_data_changed(self) -> None:
        """Desktop CRUD sonrası mobili bilgilendirmek için çağrılır."""
        with self._flag_lock:
            self._data_changed_flag = True

    def _notify_change(self):
        with self._flag_lock:
            self._data_changed_flag = True
        if self._on_data_changed:
            try:
                self._on_data_changed()
            except Exception:
                pass

    # ── Utility ───────────────────────────────────────────────────────────

    def get_server_ip(self) -> Optional[str]:
        """Sunucunun yerel ağ IP adresini döner."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return None
