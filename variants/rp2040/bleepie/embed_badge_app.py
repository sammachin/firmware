"""PlatformIO pre-build script: embed the Tildagon badge app into the firmware.

Builds a LittleFS image containing badge-app/app.py and generates a C header
(variants/rp2040/bleepie/eeprom_image.h) with the image as a byte array. The
core1 hexpansion emulation (src/platform/rp2xx0/bleepie_hexpansion.cpp) serves
this image over the emulated I2C EEPROM so a Tildagon badge loads the app.

512-byte LittleFS blocks match the Tildagon badge firmware's expectation for
EEPROMs >= 8KB. Mirrors the standalone bleepie/BleepieMeshCore embed script,
adapted for the Meshtastic fork's variant directory layout.
"""

Import("env")  # noqa: F821
import os, sys, hashlib

VARIANT_DIR = os.path.join(env.subst("$PROJECT_DIR"), "variants", "rp2040", "bleepie")  # noqa: F821
APP_PY = os.path.join(VARIANT_DIR, "badge-app", "app.py")
OUT_HEADER = os.path.join(VARIANT_DIR, "eeprom_image.h")
HASH_FILE = os.path.join(env.subst("$BUILD_DIR"), "badge_app.md5")  # noqa: F821

BLOCK_SIZE = 512
FS_OFFSET = 64
EEPROM_SIZE = 65536
BLOCK_COUNT = (EEPROM_SIZE - FS_OFFSET) // BLOCK_SIZE  # 127


def app_hash():
    if not os.path.exists(APP_PY):
        return None
    with open(APP_PY, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def saved_hash():
    try:
        with open(HASH_FILE) as f:
            return f.read().strip()
    except FileNotFoundError:
        return None


def write_empty_header():
    with open(OUT_HEADER, "w") as f:
        f.write("// Auto-generated — no badge app embedded\n")
        f.write("#pragma once\n#include <stdint.h>\n\n")
        f.write("#define EEPROM_IMAGE_SIZE 0\n")
        f.write("#define EEPROM_IMAGE_HASH 0\n")


def write_image_header(image):
    import binascii

    crc = binascii.crc32(image) & 0xFFFFFFFF
    with open(OUT_HEADER, "w") as f:
        f.write("// Auto-generated from variants/rp2040/bleepie/badge-app/app.py — do not edit\n")
        f.write("#pragma once\n#include <stdint.h>\n\n")
        f.write("#define EEPROM_IMAGE_SIZE %d\n" % len(image))
        f.write("#define EEPROM_IMAGE_HASH 0x%08XU\n\n" % crc)
        f.write("static const uint8_t eeprom_image[] = {\n")
        for i in range(0, len(image), 16):
            chunk = image[i : i + 16]
            f.write("    " + ", ".join("0x%02x" % b for b in chunk) + ",\n")
        f.write("};\n")
    return crc


ah = app_hash()
sh = saved_hash()

if ah == sh and os.path.exists(OUT_HEADER):
    print("[embed_badge_app] app.py unchanged, skipping image generation")
else:
    if ah is None:
        print("[embed_badge_app] No badge-app/app.py found, generating empty header")
        write_empty_header()
        if os.path.exists(HASH_FILE):
            os.remove(HASH_FILE)
    else:
        try:
            from littlefs import LittleFS
        except ImportError:
            import subprocess

            print("[embed_badge_app] Installing littlefs-python...")
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", "littlefs-python"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
                from littlefs import LittleFS
            except Exception as e:
                print("[embed_badge_app] WARNING: littlefs-python install failed: %s" % e)
                print("[embed_badge_app] Building without embedded badge app")
                write_empty_header()
                env.Exit(0)  # noqa: F821

        with open(APP_PY, "rb") as f:
            app_data = f.read()

        print("[embed_badge_app] app.py: %d bytes -> LittleFS %d x %d (%d bytes)"
              % (len(app_data), BLOCK_COUNT, BLOCK_SIZE, BLOCK_COUNT * BLOCK_SIZE))

        fs = LittleFS(block_size=BLOCK_SIZE, block_count=BLOCK_COUNT)
        with fs.open("app.py", "wb") as fh:
            fh.write(app_data)

        image = bytes(fs.context.buffer)
        crc = write_image_header(image)

        os.makedirs(os.path.dirname(HASH_FILE), exist_ok=True)
        with open(HASH_FILE, "w") as f:
            f.write(ah)

        print("[embed_badge_app] Generated %d byte image (CRC32: 0x%08X)" % (len(image), crc))
