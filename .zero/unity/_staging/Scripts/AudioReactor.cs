using UnityEngine;

namespace ZeroOS
{
    /// <summary>
    /// Turns the currently-playing TTS audio into a smoothed 0..1 level that drives the
    /// centre beam + bloom. Attach to the same GameObject as the TTS AudioSource.
    /// </summary>
    [RequireComponent(typeof(AudioSource))]
    public class AudioReactor : MonoBehaviour
    {
        [Range(0f, 1f)] public float Level { get; private set; }
        public float gain = 6f;
        public float smoothing = 0.18f;

        AudioSource _src;
        readonly float[] _samples = new float[256];

        void Awake() { _src = GetComponent<AudioSource>(); }

        void Update()
        {
            float target = 0f;
            if (_src != null && _src.isPlaying)
            {
                _src.GetOutputData(_samples, 0);
                float sum = 0f;
                for (int i = 0; i < _samples.Length; i++) sum += _samples[i] * _samples[i];
                float rms = Mathf.Sqrt(sum / _samples.Length);
                target = Mathf.Clamp01(rms * gain);
            }
            Level = Mathf.Lerp(Level, target, smoothing);
        }
    }
}
