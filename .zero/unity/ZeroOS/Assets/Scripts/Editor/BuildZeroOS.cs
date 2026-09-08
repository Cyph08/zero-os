#if UNITY_EDITOR
using System.IO;
using UnityEditor;
using UnityEngine;

namespace ZeroOS.EditorTools
{
    /// <summary>
    /// One-click standalone build. Menu: Zero OS ▸ Build Windows (1080p).
    /// Output: ZeroOS/Builds/Windows/ZeroOS.exe
    /// </summary>
    public static class BuildZeroOS
    {
        const string OutDir = "Builds/Windows";
        const string ExeName = "ZeroOS.exe";

        [MenuItem("Zero OS/Build Windows (1080p)")]
        public static void BuildWindows()
        {
            string[] scenes = GetEnabledScenes();
            if (scenes.Length == 0)
            {
                Debug.LogError("[ZeroOS] No scenes enabled in Build Settings. Add the main scene first.");
                return;
            }

            string dir = Path.Combine(Directory.GetCurrentDirectory(), OutDir);
            Directory.CreateDirectory(dir);

            // Standalone player prefs: native res, fullscreen window, no resize jank.
            PlayerSettings.defaultScreenWidth = 1920;
            PlayerSettings.defaultScreenHeight = 1080;
            PlayerSettings.fullScreenMode = FullScreenMode.FullScreenWindow;
            PlayerSettings.allowFullscreenSwitch = true;
            PlayerSettings.useHDRDisplay = true; // request HDR swapchain where supported
            PlayerSettings.SetUseDefaultGraphicsAPIs(BuildTarget.StandaloneWindows64, true);

            var opts = new BuildPlayerOptions
            {
                scenes = scenes,
                locationPathName = Path.Combine(OutDir, ExeName),
                target = BuildTarget.StandaloneWindows64,
                options = BuildOptions.None,
            };

            var report = BuildPipeline.BuildPlayer(opts);
            var sum = report.summary;
            Debug.Log($"[ZeroOS] Build {sum.result} — {sum.totalSize} bytes -> {OutDir}/{ExeName}");
        }

        static string[] GetEnabledScenes()
        {
            var list = new System.Collections.Generic.List<string>();
            foreach (var s in EditorBuildSettings.scenes)
                if (s.enabled) list.Add(s.path);
            return list.ToArray();
        }
    }
}
#endif
