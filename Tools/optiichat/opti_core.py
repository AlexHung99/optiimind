"""Settings, model routing, local services, monitoring, and speech for OptiiChat."""
from copy import deepcopy
import json
import math
import mimetypes
import os
import re
import shutil
from pathlib import Path
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import uuid
import wave

DATA = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'OptiiChat'
COMPAT = Path(os.environ.get('LOCALAPPDATA', Path.home()))/'Programs'/'Ollama-Llama32-Compat'
DEFAULT_MODEL = 'llama3.2-vision:latest'
DEFAULTS = {
    'theme': 'system', 'tray': True, 'auto_speak': False, 'fast_image': True, 'auto_update': True,
    'text': {'model': DEFAULT_MODEL, 'device': 'CPU', 'gpu_layers': 4, 'context': 2048, 'max_tokens': 512, 'temperature': 0.6},
    'vision': {'model': DEFAULT_MODEL, 'device': 'CPU', 'gpu_layers': 4, 'context': 2048, 'max_tokens': 384, 'temperature': 0.6},
    'speech': {'provider': 'windows', 'device': 'CPU', 'endpoint': 'http://127.0.0.1:7860',
               'mode': 'design', 'instruction': '溫柔、清晰的年輕女性聲音，語氣自然親切。',
               'ref_audio': '', 'ref_text': '', 'cfg_scale': 4.0, 'seed': 42,
               'rate': 175, 'volume': 0.9, 'voice_id': '',
               'fast_all': False, 'fast_text_encoder': False, 'fast_backbone_prefill': False,
               'fast_backbone_decode': False, 'fast_depth_decoder': False, 'fast_codec': False},
}


def validate_settings(value):
    result = deepcopy(DEFAULTS)
    for key in result:
        if key in value:
            if isinstance(result[key], dict):
                result[key].update({k: v for k, v in value[key].items() if k in result[key]})
            else:
                result[key] = value[key]
    # Updates are mandatory when online. Preserve old settings files but ignore opt-outs.
    result['auto_update'] = True
    if result['theme'] not in ('system', 'light', 'dark'):
        raise ValueError('主題必須是跟隨系統、亮色或暗色。')
    for kind in ('text', 'vision'):
        item = result[kind]
        if item['device'] not in ('CPU', 'GPU') or not str(item['model']).strip():
            raise ValueError('請選擇有效模型及 CPU／GPU。')
        for key, lo, hi in [('context', 512, 32768), ('max_tokens', 1, 8192), ('gpu_layers', -1, 999)]:
            item[key] = int(item[key])
            if not lo <= item[key] <= hi:
                raise ValueError(f'{kind} / {key} 必須介於 {lo} 到 {hi}。')
        item['temperature'] = float(item['temperature'])
        if not math.isfinite(item['temperature']) or not 0 <= item['temperature'] <= 2:
            raise ValueError('Temperature 必須介於 0 到 2。')
    speech = result['speech']
    if speech['provider'] not in ('windows', 'breeze') or speech['mode'] not in ('design', 'clone'):
        raise ValueError('無效的語音引擎或模式。')
    if speech['provider'] == 'breeze' and speech['device'] != 'GPU':
        raise ValueError('Breeze-TTS-2 官方推論程式僅支援 CUDA GPU，不能以 CPU 執行。')
    if speech['provider'] == 'windows' and speech['device'] != 'CPU':
        raise ValueError('Windows 本機語音使用 CPU。')
    parsed = urlparse(speech['endpoint'])
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('請填寫不含帳密、query 或 fragment 的 HTTP(S) 語音服務網址。')
    speech['endpoint'] = speech['endpoint'].rstrip('/')
    speech['cfg_scale'] = float(speech['cfg_scale'])
    if not math.isfinite(speech['cfg_scale']) or speech['cfg_scale'] <= 0:
        raise ValueError('CFG Scale 必須大於 0。')
    speech['seed'] = int(speech['seed'])
    if not 0 <= speech['seed'] <= 2**32-1:
        raise ValueError('Seed 必須介於 0 到 4294967295。')
    speech['rate'] = int(speech['rate'])
    speech['volume'] = float(speech['volume'])
    if not 80 <= speech['rate'] <= 350 or not 0 <= speech['volume'] <= 1:
        raise ValueError('語速須為 80～350，音量須為 0～1。')
    return result


def load_settings(path=None):
    path = Path(path or DATA/'settings.json')
    if not path.exists():
        return deepcopy(DEFAULTS)
    return validate_settings(json.loads(path.read_text(encoding='utf-8')))


def save_settings(settings, path=None):
    settings = validate_settings(settings)
    path = Path(path or DATA/'settings.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, path)
    return settings


def model_service_kind(model, catalog=()):
    info = next((item for item in catalog if item['name'] == model), {})
    family = info.get('details', {}).get('family')
    return 'vision' if family == 'mllama' or model.split('/')[-1].split(':')[0] == 'llama3.2-vision' else 'text'


def route_messages(settings, messages, mode='auto', catalog=()):
    has_image = any(message.get('images') for message in messages)
    kind = 'vision' if mode == 'vision' or (mode == 'auto' and has_image) else 'text'
    profile = settings[kind]
    service = model_service_kind(profile['model'], catalog)
    host = '127.0.0.1:11434' if service == 'text' else ('127.0.0.1:11436' if profile['device'] == 'GPU' else '127.0.0.1:11435')
    routed = deepcopy(messages)
    if kind == 'text':
        for message in routed:
            message.pop('images', None)
    options = {'num_ctx': profile['context'], 'num_predict': profile['max_tokens'],
               'temperature': profile['temperature'], 'num_batch': 64,
               'num_gpu': 0 if profile['device'] == 'CPU' else profile['gpu_layers']}
    return kind, host, profile['model'], options, routed


def json_request(url, payload=None, timeout=8):
    request = Request(url, data=None if payload is None else json.dumps(payload).encode('utf-8'),
                      headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def installed_models():
    """A failed inventory is not an empty installation: never download on read errors."""
    ensure_model_service('text', 'CPU')
    response = json_request('http://127.0.0.1:11434/api/tags')
    if not isinstance(response.get('models'), list):
        raise RuntimeError('Ollama 回傳了無效的模型清單。')
    models = []
    for item in response['models']:
        if not isinstance(item, dict) or not item.get('name'):
            raise RuntimeError('Ollama 模型清單缺少名稱。')
        item = deepcopy(item)
        if 'capabilities' not in item:
            details = json_request('http://127.0.0.1:11434/api/show', {'model': item['name']}, timeout=30)
            item['capabilities'] = details.get('capabilities', [])
        models.append(item)
    return sorted(models, key=lambda item: item['name'].lower())


def model_choices(catalog, kind):
    capability = 'vision' if kind == 'vision' else 'completion'
    return [item['name'] for item in catalog if capability in item.get('capabilities', [])]


def select_installed_defaults(settings, catalog):
    result = deepcopy(settings)
    for kind in ('text', 'vision'):
        choices = model_choices(catalog, kind)
        if choices and result[kind]['model'] not in choices:
            # Never silently run a different, user-downloaded model when a saved
            # selection disappears. The user can explicitly choose it in Settings.
            result[kind]['model'] = DEFAULT_MODEL
    return result


def validate_model_name(value):
    if not isinstance(value, str):
        raise ValueError('請輸入 Ollama 模型名稱，例如 llama3.2-vision 或 model:tag。')
    name = value.strip()
    if (len(name) > 200 or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*(?::[A-Za-z0-9][A-Za-z0-9._-]*)?', name)
            or any(part in ('', '.', '..') for part in name.split(':', 1)[0].split('/'))):
        raise ValueError('請輸入 Ollama 模型名稱，例如 llama3.2-vision 或 model:tag。')
    return name


class ModelDownload:
    """Isolate blocking registry I/O so closing/cancelling never blocks Tk."""
    def __init__(self, model='llama3.2-vision'):
        self.model = validate_model_name(model)
        self.cancelled = threading.Event()
        self.process = None

    def cancel(self):
        self.cancelled.set()
        if self.process and self.process.poll() is None:
            self.process.terminate()

    def pull(self, emit):
        if self.cancelled.is_set():
            raise RuntimeError('模型下載已取消。')
        self.process = subprocess.Popen([sys.executable, '-u', str(Path(__file__).with_name('opti_model_worker.py')), self.model],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8',
            env={**os.environ, 'PYTHONIOENCODING': 'utf-8'}, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if self.cancelled.is_set():
            self.process.terminate()
        success = False
        try:
            for line in self.process.stdout:
                if self.cancelled.is_set():
                    break
                try:
                    event = json.loads(line)
                except ValueError:
                    raise RuntimeError('下載程序回傳非預期內容：'+line[:300])
                if event.get('error'):
                    raise RuntimeError(event['error'])
                emit(event)
                success = event.get('status') == 'success'
            self.process.wait(timeout=10)
            if self.cancelled.is_set():
                raise RuntimeError('模型下載已取消；重試可接續已下載內容。')
            if self.process.returncode != 0 or not success:
                raise RuntimeError('模型下載未完成，請檢查網路與磁碟空間後重試。')
        finally:
            if self.process.poll() is None:
                self.process.terminate()
                self.process.wait(timeout=10)
            self.process.stdout.close()


def initialize_models(download, emit, ensure_default=False):
    catalog = installed_models()
    if not catalog or (ensure_default and DEFAULT_MODEL not in [item['name'] for item in catalog]):
        emit({'status': '正在從 Ollama 官方下載預設模型 llama3.2-vision（約 7.8 GB）…'})
        download.pull(emit)
        catalog = installed_models()
        if DEFAULT_MODEL not in [item['name'] for item in catalog]:
            raise RuntimeError('下載結束但找不到 llama3.2-vision，請重新整理。')
    return catalog


_service_lock = threading.Lock()


def ensure_model_service(kind, device):
    port = 11434 if kind == 'text' else (11436 if device == 'GPU' else 11435)
    url = f'http://127.0.0.1:{port}'
    with _service_lock:
        try:
            version = json_request(url+'/api/version')['version']
        except OSError:
            version = None
        if version:
            if kind == 'vision' and version != '0.24.0':
                raise RuntimeError('Vision 需要 0.24.0 相容版；此連接埠正由其他版本使用。')
            return
        executable = (Path(os.environ['LOCALAPPDATA'])/'Programs'/'Ollama'/'ollama.exe') if kind == 'text' else COMPAT/'ollama.exe'
        if kind == 'text' and not executable.exists() and shutil.which('ollama'):
            executable = Path(shutil.which('ollama'))
        if not executable.exists():
            raise RuntimeError(f'找不到 Ollama：{executable}')
        DATA.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.update(OLLAMA_HOST=f'127.0.0.1:{port}', OLLAMA_MODELS=os.environ.get('OLLAMA_MODELS', str(Path.home()/'.ollama'/'models')),
                   OLLAMA_VULKAN='1' if kind == 'vision' and device == 'GPU' else '0', OLLAMA_CONTEXT_LENGTH='2048')
        with (DATA/f'server-{port}.log').open('ab') as log:
            process = subprocess.Popen([str(executable), 'serve'], env=env, stdout=log, stderr=log,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        for _ in range(30):
            try:
                if json_request(url+'/api/version', timeout=1):
                    return
            except OSError:
                if process.poll() is not None:
                    raise RuntimeError(f'Ollama 啟動失敗，請查看 {DATA / f"server-{port}.log"}')
                time.sleep(.5)
        raise RuntimeError('Ollama 啟動逾時，請稍後再試。')


def breeze_hardware_available():
    """Gate the optional model UI on the vendor's recommended single-GPU VRAM.

    This is a hardware eligibility check, not proof a Breeze service is installed.
    Unknown hardware stays hidden; memory from multiple cards is not combined.
    """
    nvml = None
    try:
        import pynvml
        pynvml.nvmlInit()
        nvml = pynvml
        return any(
            nvml.nvmlDeviceGetMemoryInfo(nvml.nvmlDeviceGetHandleByIndex(index)).total >= 12 * 1024**3
            for index in range(nvml.nvmlDeviceGetCount())
        )
    except Exception:
        return False
    finally:
        if nvml:
            try:
                nvml.nvmlShutdown()
            except Exception:
                pass


class ResourceMonitor:
    def __init__(self):
        import psutil
        self.psutil = psutil
        self.nvml = None
        try:
            import pynvml
            pynvml.nvmlInit()
            self.nvml = pynvml
            self.gpu = pynvml.nvmlDeviceGetHandleByIndex(0)
        except Exception:
            pass
        psutil.cpu_percent()

    def sample(self):
        result = {'cpu': self.psutil.cpu_percent(), 'ram': self.psutil.virtual_memory().percent, 'gpu': None, 'vram': None}
        if self.nvml:
            try:
                result['gpu'] = self.nvml.nvmlDeviceGetUtilizationRates(self.gpu).gpu
                memory = self.nvml.nvmlDeviceGetMemoryInfo(self.gpu)
                result['vram'] = (memory.used/1024**3, memory.total/1024**3)
            except Exception:
                pass
        return result

    def close(self):
        if self.nvml:
            self.nvml.nvmlShutdown()


def multipart_speech(speech, text):
    fields = {'text': text, 'cfg_scale': str(speech['cfg_scale']), 'seed': str(speech['seed'])}
    if speech['instruction'].strip():
        fields['instruction'] = speech['instruction'].strip()
    if speech['mode'] == 'design' and not fields.get('instruction'):
        raise ValueError('Voice Design 需要填寫聲音描述。')
    reference = None
    if speech['mode'] == 'clone':
        reference = Path(speech['ref_audio'])
        if not reference.is_file() or not speech['ref_text'].strip():
            raise ValueError('Voice Clone 需要參考音檔及其正確逐字稿。')
        if reference.stat().st_size > 30*1024*1024:
            raise ValueError('參考音檔不得超過 30 MB。')
        fields['ref_text'] = speech['ref_text'].strip()
    boundary = 'Optii'+uuid.uuid4().hex
    chunks = []
    for key, value in fields.items():
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode('utf-8'))
    if reference:
        extension = reference.suffix.lower() if reference.suffix.lower() in ('.wav', '.mp3', '.flac', '.m4a', '.ogg') else '.wav'
        mime = mimetypes.guess_type(reference.name)[0] or 'application/octet-stream'
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="ref_audio"; filename="reference{extension}"\r\nContent-Type: {mime}\r\n\r\n'.encode('ascii'))
        chunks.extend([reference.read_bytes(), b'\r\n'])
    chunks.append(f'--{boundary}--\r\n'.encode('ascii'))
    return boundary, b''.join(chunks)


class SpeechJob:
    def __init__(self):
        self.cancelled = threading.Event()
        self.process = None
        self.response = None

    def cancel(self):
        self.cancelled.set()
        if self.process and self.process.poll() is None:
            self.process.terminate()

    def generate(self, speech, text):
        if not text.strip():
            raise ValueError('請先輸入要朗讀的文字，或完成一則模型回覆。')
        output_dir = DATA/'audio'
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir/(uuid.uuid4().hex+'.wav')
        job = output.with_suffix('.json')
        job.write_text(json.dumps({'text': text, 'output': str(output), **speech}, ensure_ascii=False), encoding='utf-8')
        try:
            if self.cancelled.is_set():
                raise RuntimeError('語音已取消。')
            self.process = subprocess.Popen([sys.executable, str(Path(__file__).with_name('opti_speech_worker.py')), str(job)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if self.cancelled.is_set():
                self.process.terminate()
            try:
                _, error = self.process.communicate(timeout=900)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.communicate()
                raise RuntimeError('語音生成逾時。')
            if self.cancelled.is_set():
                raise RuntimeError('語音已取消。')
            if self.process.returncode != 0:
                raise RuntimeError(error.decode('utf-8', errors='replace')[-1500:])
        except Exception:
            output.unlink(missing_ok=True)
            raise
        finally:
            job.unlink(missing_ok=True)
        with wave.open(str(output), 'rb') as audio:
            if audio.getnframes() == 0:
                raise RuntimeError('語音引擎沒有產生音訊。')
        return output


def breeze_launch_arguments(speech, model_path='PATH_TO_BREEZE_TTS_2'):
    args = ['python', '-m', 'breeze_infer.api', model_path, '--host', '127.0.0.1', '--port', '7860']
    keys = ('fast_all', 'fast_text_encoder', 'fast_backbone_prefill', 'fast_backbone_decode', 'fast_depth_decoder', 'fast_codec')
    for key in keys:
        if speech[key]:
            args.append('--'+key.replace('_', '-'))
    return args


def generate_breeze(speech, text, output):
    """Official streaming API; invoked in a killable subprocess for prompt cancellation."""
    if speech['device'] != 'GPU':
        raise ValueError('Breeze-TTS-2 官方推論只支援 CUDA GPU。')
    boundary, payload = multipart_speech(speech, text)
    request = Request(speech['endpoint']+'/v1/audio/speech', data=payload,
                      headers={'Content-Type': 'multipart/form-data; boundary='+boundary})
    with urlopen(request, timeout=900) as response:
        rate = int(response.headers.get('X-Sample-Rate', '24000'))
        if rate != 24000 or response.headers.get('X-Sample-Format', 's16le') != 's16le':
            raise RuntimeError('Breeze 回傳了非預期的音訊格式。')
        with wave.open(str(output), 'wb') as audio:
            audio.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
            carry = b''
            while True:
                data = response.read(8192)
                if not data:
                    break
                carry += data
                count = len(carry)//2*2
                audio.writeframesraw(carry[:count])
                carry = carry[count:]
            if carry:
                raise RuntimeError('Breeze 回傳的 PCM 資料不完整。')
