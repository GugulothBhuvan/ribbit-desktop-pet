import os
import wave
import threading
import pyaudio
from src.utils.logger import get_logger

logger = get_logger("AudioRecorder")

class AudioRecorder:
    """
    Singleton class to handle microphone audio recording on a background thread.
    Saves the recorded audio to a mono 16kHz WAV file.
    """
    _instance = None

    @classmethod
    def get_instance(cls) -> "AudioRecorder":
        if cls._instance is None:
            cls._instance = AudioRecorder()
        return cls._instance

    def __init__(self):
        self.p = pyaudio.PyAudio()
        self.stream = None
        self.frames = []
        self.is_recording = False
        self.record_thread = None
        self.output_filename = "speech_record.wav"
        
        # Audio parameters
        self.channels = 1
        self.rate = 16000  # 16kHz standard for ASR
        self.chunk_size = 1024

    def start_recording(self):
        """Starts a background thread to record microphone audio."""
        if self.is_recording:
            logger.warning("Recording is already in progress.")
            return

        logger.info("Starting audio recording...")
        self.frames = []
        self.is_recording = True
        
        try:
            self.stream = self.p.open(
                format=pyaudio.paInt16,
                channels=self.channels,
                rate=self.rate,
                input=True,
                frames_per_buffer=self.chunk_size
            )
        except Exception as e:
            logger.error(f"Failed to open audio input stream: {e}")
            self.is_recording = False
            raise e
            
        self.record_thread = threading.Thread(target=self._record_loop, daemon=True)
        self.record_thread.start()

    def _record_loop(self):
        """Continuous read loop executing on a background thread."""
        while self.is_recording:
            try:
                # Read chunks from the input stream
                data = self.stream.read(self.chunk_size)
                self.frames.append(data)
            except Exception as e:
                logger.error(f"Error reading audio stream: {e}")
                break

    def stop_recording(self) -> str:
        """Stops the audio recording thread and saves frames to speech_record.wav."""
        if not self.is_recording:
            logger.warning("No active recording session to stop.")
            return ""

        logger.info("Stopping audio recording...")
        self.is_recording = False
        
        if self.record_thread:
            self.record_thread.join(timeout=1.0)
            self.record_thread = None

        if self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except Exception as e:
                logger.error(f"Error closing audio stream: {e}")
            self.stream = None

        # Exclude saving if no frames collected
        if not self.frames:
            logger.warning("No audio frames captured, skipping save.")
            return ""

        # Make sure directory for output file exists
        out_dir = os.path.dirname(os.path.abspath(self.output_filename))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        try:
            with wave.open(self.output_filename, "wb") as wf:
                wf.setnchannels(self.channels)
                wf.setsampwidth(self.p.get_sample_size(pyaudio.paInt16))
                wf.setframerate(self.rate)
                wf.writeframes(b"".join(self.frames))
                
            logger.info(f"Audio recorded successfully saved to: {self.output_filename}")
            return self.output_filename
        except Exception as e:
            logger.error(f"Failed to save audio recording to file: {e}")
            return ""

    def cleanup(self):
        """Terminates the PyAudio subsystem on application shutdown."""
        self.is_recording = False
        if self.stream:
            try:
                self.stream.close()
            except Exception:
                pass
        try:
            self.p.terminate()
        except Exception:
            pass
        logger.info("AudioRecorder cleanup finalized.")
