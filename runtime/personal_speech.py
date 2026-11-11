"""Persistent speech tuning loaded outside the updatable package."""
def tune_model(model):
    if getattr(model,'_jarvis_tuned',False):
        return model
    original=model.transcribe
    def transcribe(*args,**kwargs):
        options={'initial_prompt':'Jarvis.','beam_size':5,'condition_on_previous_text':False,
                 'vad_filter':True,'vad_parameters':{'min_silence_duration_ms':700}}
        options.update(kwargs)
        return original(*args,**options)
    model.transcribe=transcribe
    model._jarvis_tuned=True
    return model

def install_speech_tuning():
    from openjarvis.speech.faster_whisper import FasterWhisperBackend
    original=FasterWhisperBackend._ensure_model
    def ensure(self):
        return tune_model(original(self))
    FasterWhisperBackend._ensure_model=ensure

    # Health is already resolved on a background thread when voice output opens.
    # Prepare English phonemization there instead of on the first spoken reply.
    from openjarvis.speech.kokoro_tts import KokoroTTSBackend
    if not getattr(KokoroTTSBackend,'_jarvis_pipeline_ready',False):
        original_health=KokoroTTSBackend.health
        def health(self):
            healthy=original_health(self)
            if healthy:
                try:self._ensure_pipeline('a')
                except Exception:
                    # Preserve the backend's normal health/fallback contract;
                    # synthesis still reports any actual voice-resource error.
                    pass
            return healthy
        KokoroTTSBackend.health=health
        KokoroTTSBackend._jarvis_pipeline_ready=True
