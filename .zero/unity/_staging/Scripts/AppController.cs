using System.Collections.Generic;
using UnityEngine;
using Newtonsoft.Json.Linq;

namespace ZeroOS
{
    /// <summary>
    /// App shell: owns the backend client + brain + audio, handles input, persona, the emotion
    /// state machine, and the ask -> reply -> TTS flow. Drives BrainMesh.
    /// For the first milestone the input box + subtitle are drawn with OnGUI (zero scene setup);
    /// a proper TMP UI comes in the app-ify pass.
    /// </summary>
    [RequireComponent(typeof(AudioSource))]
    public class AppController : MonoBehaviour
    {
        public NeuralSphere brain;
        public ZeroBackend backend;

        AudioSource _audioSrc;
        AudioReactor _reactor;
        string _input = "";
        string _subtitle = "";
        bool _online;
        string _personaName = "Zero";
        Color _personaColor;
        float _speakUntil;

        static readonly (string[] keys, string id)[] KW =
        {
            (new[]{"research","find","search","look up","what is","who is"}, "research"),
            (new[]{"code","debug","function","python","error","bug","script"}, "code"),
            (new[]{"study","explain","learn","understand","concept","course"}, "study"),
            (new[]{"email","message","write to","contact","comms","draft"}, "comms"),
            (new[]{"schedule","calendar","remind","meeting","task","plan"}, "schedule"),
            (new[]{"health","gym","sleep","water","workout","exercise"}, "health"),
            (new[]{"news","headline","today","latest"}, "news"),
            (new[]{"bci","eeg","motor imagery","brain","neural","electrode"}, "bci"),
            (new[]{"photo","image","picture","nikon","camera","jpeg"}, "photo"),
            (new[]{"career","job","cv","resume","apply","work"}, "career"),
            (new[]{"idea","brainstorm","startup","mvp"}, "brainstorm"),
            (new[]{"linkedin","network","connect","profile","recruiter"}, "linkedin"),
        };

        void Awake()
        {
            _audioSrc = GetComponent<AudioSource>();
            _audioSrc.playOnAwake = false;
            _reactor = GetComponent<AudioReactor>();
            if (_reactor == null) _reactor = gameObject.AddComponent<AudioReactor>();
            if (backend == null) backend = gameObject.AddComponent<ZeroBackend>();
            if (brain == null) brain = GetComponent<NeuralSphere>();
            _personaColor = Agents.ZeroColor;
        }

        void Start()
        {
            backend.Health(ok => _online = ok);
            backend.GetPersona((name, col) =>
            {
                if (!string.IsNullOrEmpty(name)) { _personaName = name; _personaColor = col; brain?.SetPersona(col); }
            });
            InvokeRepeating(nameof(Ping), 15f, 15f);
        }

        void Ping() => backend.Health(ok => _online = ok);

        void Update()
        {
            if (brain != null) brain.SetAudioLevel(_reactor != null ? _reactor.Level : 0f);
            if (_speakUntil > 0f && Time.time > _speakUntil && !_audioSrc.isPlaying)
            {
                _speakUntil = 0f;
                brain?.SetEmotion(Emotion.Idle);
                brain?.SetActiveAgents(null);
            }
        }

        string GuessAgent(string q)
        {
            string s = q.ToLowerInvariant();
            foreach (var (keys, id) in KW)
                foreach (var k in keys)
                    if (s.Contains(k)) return id;
            return null;
        }

        void Send()
        {
            string q = _input.Trim();
            if (string.IsNullOrEmpty(q)) return;
            _input = "";
            brain?.SetEmotion(Emotion.Thinking);
            string guess = GuessAgent(q);
            if (guess != null) brain?.SetActiveAgents(new[] { guess });
            _subtitle = "...";

            backend.Ask(q, res =>
            {
                if (res.persona_switched && res.persona != null)
                {
                    var name = res.persona.Value<string>("name");
                    if (ColorUtility.TryParseHtmlString(res.persona.Value<string>("color"), out var c))
                    { _personaName = name; _personaColor = c; brain?.SetPersona(c); }
                }
                var used = res.agents_used != null && res.agents_used.Length > 0
                    ? new List<string>(res.agents_used) : (guess != null ? new List<string> { guess } : new List<string>());
                brain?.SetActiveAgents(used);

                string reply = res.Reply;
                if (string.IsNullOrEmpty(reply)) reply = "(no response)";
                _subtitle = reply.Length > 320 ? reply.Substring(0, 320) : reply;
                Speak(reply.Length > 280 ? reply.Substring(0, 280) : reply);
            });
        }

        void Speak(string text)
        {
            backend.Tts(text, _personaName.ToLowerInvariant(), clip =>
            {
                if (clip == null) { brain?.SetEmotion(Emotion.Idle); return; }
                _audioSrc.clip = clip;
                _audioSrc.Play();
                brain?.SetEmotion(Emotion.Speaking);
                _speakUntil = Time.time + clip.length + 0.3f;
            });
        }

        void TogglePersona()
        {
            string next = _personaName.ToLowerInvariant() == "v" ? "zero" : "v";
            backend.SwitchPersona(next, (name, col) =>
            {
                if (!string.IsNullOrEmpty(name)) { _personaName = name; _personaColor = col; brain?.SetPersona(col); }
                else { _personaName = next == "v" ? "V" : "Zero"; _personaColor = next == "v" ? Agents.VColor : Agents.ZeroColor; brain?.SetPersona(_personaColor); }
            });
        }

        // ── minimal IMGUI overlay (replaced by TMP UI in app-ify) ─────────────────
        void OnGUI()
        {
            float w = Screen.width, h = Screen.height;
            var box = new GUIStyle(GUI.skin.textField) { fontSize = 18 };
            var lab = new GUIStyle(GUI.skin.label) { fontSize = 18, alignment = TextAnchor.MiddleCenter, wordWrap = true };

            // persona chip + status
            GUI.color = _personaColor;
            GUI.Label(new Rect(w / 2f - 60, 16, 120, 26), $"{_personaName.ToUpper()}", new GUIStyle(GUI.skin.label) { fontSize = 16, alignment = TextAnchor.MiddleCenter });
            GUI.color = _online ? Color.green : Color.red;
            GUI.Label(new Rect(16, h - 30, 200, 22), _online ? "● BACKEND ONLINE" : "● BACKEND OFFLINE");
            GUI.color = Color.white;

            // subtitle
            if (!string.IsNullOrEmpty(_subtitle))
            {
                GUI.color = _personaColor;
                GUI.Label(new Rect(w * 0.15f, h - 130, w * 0.7f, 60), _subtitle, lab);
                GUI.color = Color.white;
            }

            // input
            GUI.SetNextControlName("zin");
            _input = GUI.TextField(new Rect(w / 2f - 240, h - 64, 420, 32), _input, box);
            if (GUI.Button(new Rect(w / 2f + 188, h - 64, 52, 32), "▶")) Send();
            if (GUI.Button(new Rect(w / 2f - 300, h - 64, 52, 32), _personaName.ToUpper()[..1])) TogglePersona();

            var e = Event.current;
            if (e.type == EventType.KeyDown && (e.keyCode == KeyCode.Return || e.keyCode == KeyCode.KeypadEnter)
                && GUI.GetNameOfFocusedControl() == "zin")
            { Send(); e.Use(); }
        }
    }
}
