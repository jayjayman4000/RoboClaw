"""Local Ollama API adapter; no SDK dependency, API keys or shell execution."""
import json
import urllib.request
import urllib.error
from urllib.parse import urlparse


def local_endpoint(value, remote=False):
    parsed = urlparse(value)
    if parsed.scheme not in ('http', 'https') or (not parsed.hostname or (not remote and parsed.hostname not in ('localhost', '127.0.0.1', '::1'))) or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
        raise ValueError('Use a local Ollama endpoint such as http://localhost:11434')
    parsed.port  # Validate the port before issuing a request.
    return value.rstrip('/')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('AI endpoint redirects are not supported')


class OllamaBackend:
    def __init__(self, endpoint='http://localhost:11434', model=None, timeout_s=180, remote=False):
        self.endpoint = local_endpoint(endpoint, remote)
        self.remote = remote
        self.model = model
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)) or not 10 <= timeout_s <= 600:
            raise ValueError("AI timeout must be between 10 and 600 seconds")
        self.timeout_s = timeout_s
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(self, path, payload=None, timeout=60):
        data = None if payload is None else json.dumps(payload, allow_nan=False).encode()
        request = urllib.request.Request(self.endpoint + path, data=data, headers={'Content-Type':'application/json'})
        try:
            with self.opener.open(request, timeout=timeout) as response:
                raw = response.read(2_000_001)
            if len(raw)>2_000_000: raise ValueError('Ollama response exceeds size limit')
            result = json.loads(raw)
            if not isinstance(result,dict): raise ValueError('Invalid Ollama response')
            if result.get('error'): raise ValueError('Ollama: ' + str(result['error']))
            return result
        except urllib.error.HTTPError as error:
            raise ValueError(f'Ollama returned HTTP {error.code}; check model installation/tool support') from error
        except TimeoutError as error:
            raise ValueError(f'Ollama response exceeded {timeout} seconds. The model may be loading or slow; use --timeout 300 or a smaller tool-capable model.') from error
        except urllib.error.URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise ValueError(f'Ollama response exceeded {timeout} seconds. Use --timeout 300 or a smaller tool-capable model.') from error
            raise ValueError('Cannot connect to Ollama. Check the endpoint, listening address, Tailscale access and firewall.') from error
        except OSError as error:
            raise ValueError('Ollama connection failed: ' + str(error)) from error

    def models(self):
        values=self.request('/api/tags',timeout=5).get('models',[])
        if not isinstance(values,list): raise ValueError('Invalid Ollama model list')
        return [m['name'] for m in values if isinstance(m,dict) and isinstance(m.get('name'),str) and ':cloud' not in m['name']]

    def check(self):
        if not isinstance(self.model,str) or not self.model.strip() or ':cloud' in self.model:
            raise ValueError('Choose a downloaded local model')
        metadata=self.request('/api/show',{'model':self.model},timeout=10)
        if metadata.get('remote_host') or metadata.get('remote_model'):
            raise ValueError('Choose a local model; this setup does not use cloud inference')
        capabilities = metadata.get('capabilities', [])
        if not isinstance(capabilities, list) or 'tools' not in capabilities:
            raise ValueError('Selected model does not report tool support; choose a tool-capable model')
        return {'provider':'ollama','endpoint':self.endpoint,'model':self.model,'status':'configured','tool_support':True,'timeout_s':self.timeout_s,'mode':'remote' if self.remote else 'local'}

    def complete(self,messages,tools):
        messages = [dict(m) for m in messages]
        if self.model and self.model.split(':')[0] == 'qwen3':
            # Soft model hint complements the native API flag; it is not guaranteed.
            if messages and messages[0].get('role') == 'system':
                messages[0]['content'] += '\n/no_think'
            else:
                messages.insert(0, {'role':'system','content':'Answer directly and use supplied tools when needed. /no_think'})
        response=self.request('/api/chat',{'model':self.model,'messages':messages,'tools':tools,
                              'stream':False,'think':False,'keep_alive':getattr(self,'keep_alive','5m'),
                              'options':{'temperature':0,'num_predict':getattr(self,'num_predict',512),'num_ctx':getattr(self,'num_ctx',4096)}}, timeout=self.timeout_s)
        message=response.get('message')
        if not isinstance(message,dict) or message.get('role')!='assistant' or not isinstance(message.get('content',''),str):
            raise ValueError('Invalid assistant response from Ollama')
        message = dict(message)
        content = message.get('content', '')
        # Some model/templates leak a reasoning preamble ending with a lone closing tag.
        if '</think>' in content:
            content = content.rsplit('</think>', 1)[1]
        elif '<think>' in content:
            content = content.split('<think>', 1)[0]
        message['content'] = content.strip()
        return message


def configure_ai(path,config,save,endpoint=None,model=None,timeout_s=None):
    """Backward-compatible local setup entry point."""
    from .ai_backend import configure_ai as configure
    return configure(path,config,save,endpoint,model,timeout_s,mode='local')
