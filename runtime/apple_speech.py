"""Local Apple-Silicon Whisper recognition; independent of the chat provider."""
import io
import logging
import math
from pathlib import Path
import threading
from concurrent.futures import ThreadPoolExecutor
from openjarvis.core.registry import SpeechRegistry
from openjarvis.speech._stubs import SpeechBackend, TranscriptionResult, Segment

MODEL=Path.home()/'.openjarvis/models/whisper-large-v3-turbo-mlx'
MODEL_REVISION='a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb'
LOCK=threading.RLock()
# MLX arrays and GPU streams must remain on their creating thread.
GPU_WORKER=ThreadPoolExecutor(max_workers=1,thread_name_prefix='jarvis-whisper')
logger=logging.getLogger('openjarvis.speech.apple')


@SpeechRegistry.register('mlx-whisper')
class AppleWhisperBackend(SpeechBackend):
    backend_id='mlx-whisper'
    def __init__(self):
        self._ready=False
        self._fallback=None
        self._last_error=None
        self._use_cpu=False

    def _ensure(self):
        if self._ready:return
        if not (MODEL/'config.json').is_file() or not (MODEL/'weights.safetensors').is_file():
            raise RuntimeError('The local Whisper Turbo model download is incomplete.')
        import mlx.core as mx
        from mlx_whisper.transcribe import ModelHolder
        mx.set_default_device(mx.gpu)
        ModelHolder.get_model(str(MODEL),mx.float16)
        self._ready=True

    def _cpu(self):
        # Never fall back to OpenAI, Deepgram, or another billable speech API.
        if self._fallback is None:
            from openjarvis.speech.faster_whisper import FasterWhisperBackend
            self._fallback=FasterWhisperBackend(model_size='small.en',device='cpu',compute_type='int8')
        self.backend_id='faster-whisper-local-fallback'
        return self._fallback

    def health(self):
        return GPU_WORKER.submit(self._health).result()

    def _health(self):
        with LOCK:
            if self._use_cpu:return self._cpu().health()
            try:self._ensure();return True
            except Exception as error:
                self._last_error='Apple GPU load failed: '+str(error)[:600]
                logger.warning('Apple GPU speech load failed (%s); using local CPU fallback.',type(error).__name__)
                self._use_cpu=True
                return self._cpu().health()

    def transcribe(self,audio,*,format='wav',language=None):
        return GPU_WORKER.submit(self._transcribe,audio,format=format,language=language).result()

    def _transcribe(self,audio,*,format='wav',language=None):
        with LOCK:
            if self._use_cpu:return self._cpu().transcribe(audio,format=format,language=language or 'en')
            from faster_whisper.audio import decode_audio
            from faster_whisper.vad import get_speech_timestamps,VadOptions
            waveform=decode_audio(io.BytesIO(audio),sampling_rate=16000)
            duration=len(waveform)/16000
            if duration<.2:return TranscriptionResult(text='',language=language or 'en',confidence=0.,duration_seconds=duration)
            chunks=get_speech_timestamps(waveform,VadOptions(threshold=.5,min_speech_duration_ms=250,
                      min_silence_duration_ms=700,speech_pad_ms=400))
            if not chunks:return TranscriptionResult(text='',language=language or 'en',confidence=0.,duration_seconds=duration)
            # Preserve all speech and internal pauses; trim only leading/trailing silence.
            start=chunks[0]['start'];end=chunks[-1]['end'];offset=start/16000
            try:
                self._ensure()
                import mlx_whisper
                result=mlx_whisper.transcribe(waveform[start:end],path_or_hf_repo=str(MODEL),
                    language=language or 'en',task='transcribe',temperature=0.0,
                    condition_on_previous_text=False,initial_prompt='Jarvis.',
                    no_speech_threshold=.6,logprob_threshold=-1.0,
                    compression_ratio_threshold=2.4,verbose=None)
            except Exception as error:
                self._last_error='Apple GPU recognition failed: '+str(error)[:600]
                logger.exception('Apple GPU transcription failed; using local CPU fallback.')
                self._use_cpu=True
                return self._cpu().transcribe(audio,format=format,language=language or 'en')
            segments=[];probabilities=[]
            for value in result.get('segments',[]):
                text=value.get('text','').strip()
                if not text:continue
                confidence=min(1.,math.exp(float(value.get('avg_logprob',-1.))))
                probabilities.append(confidence)
                segments.append(Segment(text=text,start=float(value['start'])+offset,
                                        end=float(value['end'])+offset,confidence=confidence))
            self._last_error=None
            return TranscriptionResult(text=' '.join(s.text for s in segments),language=result.get('language',language or 'en'),
                confidence=sum(probabilities)/len(probabilities) if probabilities else 0.,
                duration_seconds=duration,segments=segments)

    def last_error(self):return self._last_error
    def supported_formats(self):return ['wav','mp3','m4a','ogg','flac','webm']
