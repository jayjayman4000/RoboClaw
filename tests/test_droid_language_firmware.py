"""Native checks for the Pi -> body -> head droid-language path."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('g++'), 'g++ unavailable for native firmware logic checks')
class DroidLanguageFirmwareTest(unittest.TestCase):
    def test_body_transport_and_non_blocking_head_sequence(self):
        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as directory:
            for role in ('head', 'body'):
                source = root / f'tests/{role}_droid_language_firmware.cpp'
                binary = Path(directory) / role
                subprocess.run(
                    ['g++', '-std=c++17', '-I' + str(root / 'tests/firmware_stubs'), str(source), '-o', str(binary)],
                    check=True, capture_output=True, text=True,
                )
                subprocess.run([str(binary)], check=True, capture_output=True, text=True)


if __name__ == '__main__':
    unittest.main()
