"""Persistent local Piper voice adapter, kept outside the updatable package."""
import io
import logging
import threading
import time
import wave
from pathlib import Path

from openjarvis.core.registry import TTSRegistry
from openjarvis.speech.tts import TTSBackend, TTSResult

VOICE = 'en_US-ryan-medium'
MODEL = Path.home() / '.openjarvis/models/piper' / (VOICE + '.onnx')


@TTSRegistry.register('piper')
class PiperTTSBackend(TTSBackend):
    backend_id = 'piper'

    def __init__(self, **kwargs):
        self._voice = None
        self._lock = threading.RLock()

    def _load(self):
        if self._voice is None:
            if not MODEL.is_file() or not Path(str(MODEL) + '.json').is_file():
                raise RuntimeError('The local Piper voice files are missing.')
            import onnxruntime
            onnxruntime.disable_telemetry_events()
            from piper import PiperVoice
            self._voice = PiperVoice.load(MODEL, use_cuda=False, download_dir=MODEL.parent)
        return self._voice

    def health(self):
        with self._lock:
            try:
                self._load()
                return True
            except Exception:
                logging.getLogger(__name__).exception('Local Piper voice unavailable')
                return False

    def available_voices(self):
        return [VOICE]

    def synthesize(self, text, *, voice_id='', speed=1.0, output_format='wav'):
        if output_format != 'wav':
            raise ValueError('Piper voice output supports WAV only.')
        # Old tabs retain Kokoro's selected voice; map that saved default explicitly.
        if voice_id not in ('', VOICE, 'am_michael', 'en_GB-northern_english_male-medium'):
            raise ValueError('Select the installed Piper US male voice.')
        if not 0.5 <= speed <= 2.0:
            raise ValueError('Voice speed must be between 0.5 and 2.0.')
        from piper import SynthesisConfig
        started = time.monotonic()
        with self._lock:
            voice = self._load()
            buf = io.BytesIO()
            with wave.open(buf, 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(voice.config.sample_rate)
                voice.synthesize_wav(text, wav, syn_config=SynthesisConfig(length_scale=1.0 / speed))
            audio = buf.getvalue()
        with wave.open(io.BytesIO(audio), 'rb') as wav:
            duration = wav.getnframes() / wav.getframerate()
        elapsed = time.monotonic() - started
        logging.getLogger('openjarvis.latency').info(
            'Piper synthesis_s=%.3f audio_s=%.3f chars=%d', elapsed, duration, len(text))
        from response_speed import record
        record('voice_synthesis',elapsed)
        return TTSResult(audio=audio, format='wav', voice_id=VOICE,
                         sample_rate=voice.config.sample_rate, duration_seconds=duration,
                         metadata={'backend': 'piper', 'synthesis_seconds': elapsed})

    def close(self):
        with self._lock:
            self._voice = None


# Never fall through to a paid speech service if a local voice is unavailable.
from openjarvis.speech import _tts_discovery
_tts_discovery.TTS_BACKEND_ORDER = ('piper', 'kokoro')
_tts_discovery.BACKEND_DEFAULT_VOICE['piper'] = VOICE
