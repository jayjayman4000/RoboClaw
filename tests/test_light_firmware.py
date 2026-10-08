"""Native firmware logic checks using API stubs; not an ESP32 toolchain build."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

@unittest.skipUnless(shutil.which('g++'),'g++ unavailable for native firmware logic checks')
class FirmwareLogicTest(unittest.TestCase):
    def test_head_and_body_light_protocol(self):
        root=Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as directory:
            for role in ('head','body'):
                binary=Path(directory)/role
                subprocess.run(['g++','-std=c++17','-I'+str(root/'tests/firmware_stubs'),str(root/f'tests/{role}_light_firmware.cpp'),'-o',str(binary)],check=True,capture_output=True,text=True)
                subprocess.run([str(binary)],check=True,capture_output=True,text=True)
