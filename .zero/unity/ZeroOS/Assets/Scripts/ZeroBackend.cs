using System;
using System.Collections;
using System.IO;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace ZeroOS
{
    /// <summary>Result of POST /ask (fields are best-effort; backend varies by agent).</summary>
    public class AskResult
    {
        public string response;
        public string result;
        public string explanation;
        public string summary;
        public string error;
        public string[] agents_used;
        public bool persona_switched;
        public string model_used;
        public int duration_ms;
        public JObject persona;   // {name,color,placeholder}

        public string Reply =>
            !string.IsNullOrEmpty(response) ? response :
            !string.IsNullOrEmpty(result) ? result :
            !string.IsNullOrEmpty(explanation) ? explanation :
            !string.IsNullOrEmpty(summary) ? summary :
            !string.IsNullOrEmpty(error) ? error : "";
    }

    /// <summary>
    /// HTTP client for the Zero OS FastAPI backend (localhost:8000).
    /// Same endpoints the web app used: /ask {input}, /tts {text,persona}, /persona/*, /health.
    /// Attach to a GameObject; call the methods with callbacks (coroutine-based).
    /// </summary>
    public class ZeroBackend : MonoBehaviour
    {
        public string baseUrl = "http://localhost:8000";

        public void Health(Action<bool> done)
        {
            StartCoroutine(GetCo($"{baseUrl}/health", 2.5f,
                ok => done?.Invoke(ok != null),
                _ => done?.Invoke(false)));
        }

        public void GetPersona(Action<string, Color> done)
        {
            StartCoroutine(GetCo($"{baseUrl}/persona/current", 4f, txt =>
            {
                var (name, col) = ParsePersona(txt);
                done?.Invoke(name, col);
            }, _ => { }));
        }

        public void SwitchPersona(string next, Action<string, Color> done)
        {
            StartCoroutine(PostCo($"{baseUrl}/persona/switch/{next}", "{}", 6f, txt =>
            {
                try
                {
                    var o = JObject.Parse(txt);
                    var p = o["persona"] as JObject;
                    if (p != null)
                    {
                        var name = p.Value<string>("name");
                        ColorUtility.TryParseHtmlString(p.Value<string>("color"), out var c);
                        done?.Invoke(name, c);
                        return;
                    }
                }
                catch { }
                done?.Invoke(null, default);
            }, _ => done?.Invoke(null, default)));
        }

        public void Ask(string input, Action<AskResult> done)
        {
            string body = JsonConvert.SerializeObject(new { input });
            StartCoroutine(PostCo($"{baseUrl}/ask", body, 120f, txt =>
            {
                AskResult r = null;
                try { r = JsonConvert.DeserializeObject<AskResult>(txt); } catch { }
                done?.Invoke(r ?? new AskResult { error = "parse_error" });
            }, err => done?.Invoke(new AskResult { error = err })));
        }

        /// <summary>POST /tts -> mp3 bytes -> temp file -> AudioClip (MPEG).</summary>
        public void Tts(string text, string persona, Action<AudioClip> done)
        {
            string body = JsonConvert.SerializeObject(new { text, persona });
            StartCoroutine(TtsCo($"{baseUrl}/tts", body, done));
        }

        // ── coroutines ─────────────────────────────────────────────────────────
        IEnumerator GetCo(string url, float timeout, Action<string> ok, Action<string> fail)
        {
            using var req = UnityWebRequest.Get(url);
            req.timeout = Mathf.CeilToInt(timeout);
            yield return req.SendWebRequest();
            if (req.result == UnityWebRequest.Result.Success) ok?.Invoke(req.downloadHandler.text);
            else fail?.Invoke(req.error);
        }

        IEnumerator PostCo(string url, string json, float timeout, Action<string> ok, Action<string> fail)
        {
            using var req = new UnityWebRequest(url, "POST");
            req.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(json));
            req.downloadHandler = new DownloadHandlerBuffer();
            req.SetRequestHeader("Content-Type", "application/json");
            req.timeout = Mathf.CeilToInt(timeout);
            yield return req.SendWebRequest();
            if (req.result == UnityWebRequest.Result.Success) ok?.Invoke(req.downloadHandler.text);
            else fail?.Invoke(req.error);
        }

        IEnumerator TtsCo(string url, string json, Action<AudioClip> done)
        {
            byte[] audio = null;
            using (var req = new UnityWebRequest(url, "POST"))
            {
                req.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(json));
                req.downloadHandler = new DownloadHandlerBuffer();
                req.SetRequestHeader("Content-Type", "application/json");
                req.timeout = 60;
                yield return req.SendWebRequest();
                if (req.result == UnityWebRequest.Result.Success) audio = req.downloadHandler.data;
            }
            if (audio == null || audio.Length == 0) { done?.Invoke(null); yield break; }

            string tmp = Path.Combine(Application.temporaryCachePath, "zero_tts.mp3");
            File.WriteAllBytes(tmp, audio);
            using var clipReq = UnityWebRequestMultimedia.GetAudioClip("file://" + tmp, AudioType.MPEG);
            yield return clipReq.SendWebRequest();
            if (clipReq.result == UnityWebRequest.Result.Success)
                done?.Invoke(DownloadHandlerAudioClip.GetContent(clipReq));
            else
                done?.Invoke(null);
        }

        static (string, Color) ParsePersona(string txt)
        {
            try
            {
                var o = JObject.Parse(txt);
                var name = o.Value<string>("name");
                ColorUtility.TryParseHtmlString(o.Value<string>("color"), out var c);
                return (name, c);
            }
            catch { return (null, default); }
        }
    }
}
