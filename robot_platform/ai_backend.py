"""Selectable AI transport. Credentials stay in environment variables."""
import json
import os
import re
import socket
from urllib.parse import urlparse
from .ollama_backend import OllamaBackend, local_endpoint


class APIBackend(OllamaBackend):
    """HTTPS OpenAI-compatible Chat Completions, including tool call IDs."""
    def __init__(self, endpoint, model, timeout_s=180, api_key_env='OPENAI_API_KEY'):
        parsed = urlparse(endpoint)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or
                parsed.password or parsed.query or parsed.fragment):
            raise ValueError('Hosted API endpoint must be HTTPS without embedded credentials')
        parsed.port
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', api_key_env):
            raise ValueError('Enter an environment variable name for the API key')
        super().__init__('http://localhost:11434', model, timeout_s)
        self.endpoint = endpoint.rstrip('/')
        self.api_key_env = api_key_env

    def request(self, path, payload=None, timeout=60):
        key = os.environ.get(self.api_key_env)
        if not key:
            raise ValueError(f'Set {self.api_key_env} in this terminal before using the hosted API')
        # Separate opener per request: never mutate headers on a shared transport.
        import urllib.request
        from .ollama_backend import NoRedirect
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        opener.addheaders = [('Authorization', 'Bearer ' + key)]
        previous = self.opener
        self.opener = opener
        try:
            return super().request(path, payload, timeout)
        except ValueError as error:
            # A service may echo submitted credentials in an error body.
            raise ValueError(str(error).replace(key, "[redacted]")) from None
        finally:
            self.opener = previous

    def models(self):
        values = self.request('/models', timeout=10).get('data')
        if not isinstance(values, list):
            raise ValueError('Invalid hosted API model list')
        return [item['id'] for item in values if isinstance(item, dict) and isinstance(item.get('id'), str)]

    def check(self):
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError('Choose a hosted model with function/tool calling support')
        if not os.environ.get(self.api_key_env):
            raise ValueError(f'Set {self.api_key_env} in this terminal first')
        # Metadata cannot prove tool support; setup probes it without executing tools.
        return {'provider':'openai-compatible','mode':'api','endpoint':self.endpoint,
                'model':self.model,'api_key_env':self.api_key_env,'timeout_s':self.timeout_s,
                'status':'configured','tool_support':'unverified'}

    def complete(self, messages, tools):
        converted = []
        for original in messages:
            item = dict(original)
            item.pop('tool_name', None)
            if item.get('role') == 'assistant':
                calls = item.get('tool_calls') or []
                if calls:
                    item['tool_calls'] = []
                    for call in calls:
                        fn = dict(call['function'])
                        if not isinstance(fn.get('arguments'), str):
                            fn['arguments'] = json.dumps(fn.get('arguments', {}), allow_nan=False)
                        item['tool_calls'].append({'id':call['id'],'type':'function','function':fn})
                else:
                    item.pop('tool_calls', None)
            converted.append(item)
        payload = {'model':self.model,'messages':converted,'stream':False}
        if tools:payload['tools'] = tools
        result = self.request('/chat/completions', payload, self.timeout_s)
        try:message = dict(result['choices'][0]['message'])
        except (KeyError, IndexError, TypeError, ValueError) as error:
            raise ValueError('Invalid hosted API assistant response') from error
        if message.get('role') != 'assistant':raise ValueError('Invalid assistant role')
        message['content'] = message.get('content') or ''
        if not isinstance(message['content'], str):raise ValueError('Invalid assistant content')
        calls = message.get('tool_calls') or []
        if not isinstance(calls,list):raise ValueError('Invalid tool calls')
        for call in calls:
            if not isinstance(call,dict) or not isinstance(call.get('id'),str) or not call['id'] or not isinstance(call.get('function'),dict):
                raise ValueError('Invalid hosted API tool call ID/function')
        return message


def backend_from_settings(settings, timeout_s=None):
    timeout = timeout_s if timeout_s is not None else settings.get('timeout_s',180)
    if settings.get('provider') == 'ollama':
        return OllamaBackend(settings.get('endpoint','http://localhost:11434'),settings.get('model'),timeout,settings.get('mode','local')=='remote')
    if settings.get('provider') == 'openai-compatible':
        return APIBackend(settings['endpoint'],settings.get('model'),timeout,settings.get('api_key_env','OPENAI_API_KEY'))
    raise ValueError('Run robot ai setup first')


def configure_ai(path, config, save, endpoint=None, model=None, timeout_s=None, mode=None, api_key_env=None, network=None):
    from .setup import choose, yes
    old = config.get('ai_backend', {})
    if mode is None:
        mode = ['local','remote','api'][choose('AI connection', ['Local Ollama on this computer','Remote Ollama through Tailscale or LAN','Hosted API with an API key (OpenAI-compatible)'])]
    if mode == 'remote':
        network = network or ['tailscale','direct'][choose('Remote network', ['Tailscale (check/install and connect first)','Direct LAN or existing network'])]
        if network == 'tailscale':
            from .tailscale_setup import ensure_tailscale
            ensure_tailscale()
    default = old.get('endpoint') if old.get('mode','local') == mode else None
    default = default or {'local':'http://localhost:11434','remote':'','api':'https://api.openai.com/v1'}[mode]
    endpoint = endpoint or input(f'AI endpoint [{default}]: ').strip() or default
    timeout = timeout_s if timeout_s is not None else old.get('timeout_s',180)
    if mode == 'api':
        env = api_key_env or input('API key environment variable [OPENAI_API_KEY]: ').strip() or 'OPENAI_API_KEY'
        print(f'The key is read from {env}; its value is never saved in robot.json.')
        backend = APIBackend(endpoint,model,timeout,env)
    else:
        backend = OllamaBackend(endpoint,model,timeout,mode=='remote')
    if model is None:
        names = backend.models()
        if not names:raise ValueError('No models available on the selected endpoint')
        backend.model = names[choose('Available models', names)]
    settings = backend.check()
    if mode == "remote":settings["network"] = network
    if mode == 'api':
        # Explicit tool probe, no hardware runtime and no action dispatch.
        tool = {'type':'function','function':{'name':'connection_probe','description':'Confirm API tool calling','parameters':{'type':'object','properties':{},'additionalProperties':False}}}
        result = backend.complete([{'role':'user','content':'Call connection_probe with no arguments.'}], [tool])
        calls = result.get('tool_calls') or []
        if len(calls)!=1 or calls[0]['function'].get('name')!='connection_probe':
            raise ValueError('Model did not complete the tool support probe; choose a tool-capable model')
        settings['tool_support'] = True
    print(f'AI: {mode} | model: {backend.model} | endpoint: {backend.endpoint}')
    if not yes('Save AI configuration?'):
        print('Cancelled. Configuration unchanged.')
        return False
    save(path, {**config,'ai_backend':settings})
    print('Saved. Next: robot ai test; robot chat --device BodyModule --debug')
    return True


def doctor(settings, endpoint=None, mode=None):
    """Read-only DNS, TCP and HTTP checks; never run inference or hardware actions."""
    mode = mode or settings.get('mode','local')
    endpoint = endpoint or settings.get('endpoint','http://localhost:11434')
    report = {'endpoint':endpoint,'mode':mode,'ok':False,'checks':[]}
    stage = 'endpoint'
    try:
        if mode == 'api':
            backend = APIBackend(endpoint, settings.get('model'), api_key_env=settings.get('api_key_env','OPENAI_API_KEY'))
        else:backend = OllamaBackend(endpoint,remote=mode=='remote')
        parsed = urlparse(backend.endpoint)
        port = parsed.port or (443 if parsed.scheme=='https' else 80)
        stage = 'dns'
        addresses = socket.getaddrinfo(parsed.hostname,port,type=socket.SOCK_STREAM)
        report['checks'].append({'stage':stage,'ok':True,'addresses':sorted({item[4][0] for item in addresses})})
        stage = 'tcp'
        with socket.create_connection((parsed.hostname,port),timeout=5):pass
        report['checks'].append({'stage':stage,'ok':True,'port':port})
        stage = 'api'
        if mode != 'api':
            version = backend.request('/api/version',timeout=5).get('version')
            if not isinstance(version,str) or not version:raise ValueError('Endpoint did not return an Ollama version')
            report['version'] = version
        report['models'] = backend.models()
        report['checks'].append({'stage':stage,'ok':True})
        report['ok'] = True
    except (ValueError, OSError) as error:
        report['checks'].append({'stage':stage,'ok':False,'error':str(error)})
        report['hint'] = 'DNS/TCP failure: check Tailscale, server listener and firewall. API failure: check service, HTTPS/authentication and endpoint. A timeout alone does not identify which security rule blocked it.'
    return report
