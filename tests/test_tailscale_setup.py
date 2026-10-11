import unittest
from unittest.mock import patch, Mock
from contextlib import redirect_stdout
from io import StringIO
from robot_platform.tailscale_setup import ensure_tailscale, install_tailscale, find_tailscale
from robot_platform.ai_backend import configure_ai
from robot_platform.ollama_backend import OllamaBackend

class TailscaleTest(unittest.TestCase):
    def test_existing_connected_install_skipped(self):
        with patch('robot_platform.tailscale_setup.find_tailscale',return_value='tailscale'),patch('robot_platform.tailscale_setup.status',return_value='Running'),patch('robot_platform.tailscale_setup.install_tailscale') as install,redirect_stdout(StringIO()):ensure_tailscale()
        install.assert_not_called()
    def test_missing_install_then_recheck(self):
        with patch('robot_platform.tailscale_setup.find_tailscale',side_effect=[None,'tailscale']),patch('robot_platform.tailscale_setup.status',return_value='Running'),patch('robot_platform.tailscale_setup.install_tailscale') as install,redirect_stdout(StringIO()):ensure_tailscale()
        install.assert_called_once()
    def test_disconnected_windows_requires_running_after_login(self):
        with patch('robot_platform.tailscale_setup.find_tailscale',return_value='tailscale'),patch('robot_platform.tailscale_setup.platform.system',return_value='Windows'),patch('robot_platform.tailscale_setup.status',side_effect=['NeedsLogin','Stopped']),patch('builtins.input',return_value=''),redirect_stdout(StringIO()),self.assertRaisesRegex(ValueError,'not connected'):ensure_tailscale()
    def test_install_failure_before_endpoint_prompt(self):
        with patch('robot_platform.tailscale_setup.ensure_tailscale',side_effect=ValueError('install failed')),patch('builtins.input') as prompt,self.assertRaisesRegex(ValueError,'install failed'):
            configure_ai('unused',{},Mock(),mode='remote',network='tailscale')
        prompt.assert_not_called()
    def test_tailscale_before_endpoint_and_remote_reminder(self):
        events=[]
        with patch('robot_platform.tailscale_setup.ensure_tailscale',side_effect=lambda:events.append('tailscale')),patch('builtins.input',side_effect=lambda p:events.append(p) or ('http://100.111.212.1:11434' if 'endpoint' in p else 'n')),patch.object(OllamaBackend,'check',return_value={}),redirect_stdout(StringIO()):
            configure_ai('unused',{},Mock(),model='test',mode='remote',network='tailscale')
        self.assertEqual(events[0],'tailscale');self.assertIn('endpoint',events[1])
    def test_windows_install_uses_exact_package(self):
        with patch('robot_platform.tailscale_setup.platform.system',return_value='Windows'),patch('robot_platform.tailscale_setup.shutil.which',return_value='winget'),patch('robot_platform.tailscale_setup.run') as run,redirect_stdout(StringIO()):install_tailscale()
        self.assertIn('Tailscale.Tailscale',run.call_args.args[0]);self.assertIn('--exact',run.call_args.args[0])
    def test_linux_script_runs_without_shell_interpolation(self):
        response=Mock();response.read.return_value=b'# test';response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
        with patch('robot_platform.tailscale_setup.platform.system',return_value='Linux'),patch('robot_platform.tailscale_setup.os.geteuid',return_value=1000,create=True),patch('robot_platform.tailscale_setup.shutil.which',return_value='sudo'),patch('robot_platform.tailscale_setup.urllib.request.urlopen',return_value=response),patch('robot_platform.tailscale_setup.run') as run,redirect_stdout(StringIO()):install_tailscale()
        self.assertEqual(run.call_args.args[0][:2],['sudo','sh'])
    def test_windows_cli_not_in_path(self):
        with patch('robot_platform.tailscale_setup.shutil.which',return_value=None),patch('robot_platform.tailscale_setup.platform.system',return_value='Windows'),patch('robot_platform.tailscale_setup.Path.is_file',return_value=True):
            self.assertTrue(find_tailscale().endswith('tailscale.exe'))
