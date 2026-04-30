#!/usr/bin/env python3
"""
VAPID Anahtar Üreteci — Web Push Bildirimleri için
Bir kez çalıştır, çıktıyı /etc/jarvis.env'e ekle
"""

def generate_vapid():
    try:
        from py_vapid import Vapid
        v = Vapid()
        v.generate_keys()
        priv = v.private_pem().decode()
        pub  = v.public_key.public_bytes(
            __import__('cryptography.hazmat.primitives.serialization',
                       fromlist=['Encoding','PublicFormat']).Encoding.X962,
            __import__('cryptography.hazmat.primitives.serialization',
                       fromlist=['Encoding','PublicFormat']).PublicFormat.UncompressedPoint
        )
        import base64
        pub_b64 = base64.urlsafe_b64encode(pub).decode().rstrip("=")
        return priv, pub_b64
    except ImportError:
        pass

    try:
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives.serialization import (
            Encoding, PublicFormat, PrivateFormat, NoEncryption)
        import base64

        priv_key = ec.generate_private_key(ec.SECP256R1(), default_backend())
        pub_key  = priv_key.public_key()

        priv_pem = priv_key.private_bytes(
            Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption()
        ).decode()
        pub_raw = pub_key.public_bytes(
            Encoding.X962, PublicFormat.UncompressedPoint)
        pub_b64 = base64.urlsafe_b64encode(pub_raw).decode().rstrip("=")

        return priv_pem, pub_b64
    except Exception as e:
        print(f"Hata: {e}")
        return None, None

if __name__ == "__main__":
    print("VAPID anahtarları üretiliyor...")
    priv, pub = generate_vapid()
    if priv and pub:
        print("\n" + "="*60)
        print("  /etc/jarvis.env dosyasına şunları ekleyin:")
        print("="*60)
        print(f"\nVAPID_PUBLIC_KEY={pub}")
        print(f"\nVAPID_PRIVATE_KEY={priv.strip()}")
        print(f"\nVAPID_EMAIL=mailto:sizin@emailiniz.com")
        print("="*60)
        # Otomatik env dosyasına yaz
        import os
        env_file = "/etc/jarvis.env"
        if os.path.exists(env_file):
            ans = input(f"\n{env_file} dosyasına otomatik eklensin mi? [E/h]: ")
            if ans.lower() in ("", "e", "y"):
                with open(env_file, "a") as f:
                    f.write(f"\nVAPID_PUBLIC_KEY={pub}\n")
                    f.write(f"VAPID_PRIVATE_KEY={priv.strip()}\n")
                    f.write("VAPID_EMAIL=mailto:jarvis@localhost\n")
                os.system("sudo systemctl restart jarvis")
                print("✓ Eklendi ve servis yeniden başlatıldı.")
    else:
        print("Anahtar üretilemedi.")
        print("Kurun: pip install pywebpush cryptography")
