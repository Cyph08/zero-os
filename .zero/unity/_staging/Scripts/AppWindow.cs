using UnityEngine;

namespace ZeroOS
{
    /// <summary>
    /// Window / display setup: 1920×1080, 144 fps target, optional HDR display output,
    /// fullscreen toggle (F11). Attach to a bootstrap GameObject in the scene.
    /// </summary>
    public class AppWindow : MonoBehaviour
    {
        public int targetFps = 144;
        public int width = 1920;
        public int height = 1080;
        public bool startFullscreen = false;
        [Tooltip("0 = uncapped (use targetFps), 1 = sync to display refresh")]
        public int vSyncCount = 0;
        public bool requestHdrOutput = true;

        void Start()
        {
            QualitySettings.vSyncCount = vSyncCount;
            Application.targetFrameRate = targetFps;

            var mode = startFullscreen ? FullScreenMode.FullScreenWindow : FullScreenMode.Windowed;
            Screen.SetResolution(width, height, mode);

            if (requestHdrOutput) TryEnableHdr();
        }

        void Update()
        {
            if (Input.GetKeyDown(KeyCode.F11)) ToggleFullscreen();
        }

        public void ToggleFullscreen()
        {
            bool full = Screen.fullScreenMode != FullScreenMode.Windowed;
            Screen.SetResolution(width, height, full ? FullScreenMode.Windowed : FullScreenMode.FullScreenWindow);
        }

        static void TryEnableHdr()
        {
            // HDR display output is enabled via Player Settings (useHDRDisplay, set by the build
            // script) + the swapchain; at runtime we can only read the status here.
            var hdr = HDROutputSettings.main;
            if (hdr != null && hdr.available)
                Debug.Log($"[ZeroOS] HDR display available — active={hdr.active}. " +
                          "Enable 'Use HDR Display Output' in Player Settings for the HDR swapchain.");
            else
                Debug.Log("[ZeroOS] HDR display output not available on this display/OS.");
        }
    }
}
