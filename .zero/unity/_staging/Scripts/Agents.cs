using UnityEngine;

namespace ZeroOS
{
    /// <summary>One department agent: id, display name, function, brand colour.</summary>
    [System.Serializable]
    public struct AgentDef
    {
        public string id;
        public string name;
        public string fn;
        public Color color;
        public AgentDef(string id, string name, string fn, string hex)
        {
            this.id = id; this.name = name; this.fn = fn;
            ColorUtility.TryParseHtmlString(hex, out color);
        }
    }

    public enum Emotion { Idle, Listening, Thinking, Speaking }

    /// <summary>
    /// Agent roster + persona palette + hue grading + brain geometry.
    /// Ported 1:1 from the web build's agents.ts so the design is identical.
    /// </summary>
    public static class Agents
    {
        // LEFT lobe (Logic) = first 6, RIGHT lobe (Creative) = last 6.
        public static readonly AgentDef[] All =
        {
            new AgentDef("research",   "Iris",    "Deep Research", "#00e5ff"),
            new AgentDef("career",     "Maven",   "Career",        "#ff6b35"),
            new AgentDef("schedule",   "Chrono",  "Scheduler",     "#b39ddb"),
            new AgentDef("brainstorm", "Spark",   "Brainstorm",    "#ffeb3b"),
            new AgentDef("code",       "Forge",   "Code",          "#69f0ae"),
            new AgentDef("study",      "Sage",    "Study",         "#80deea"),
            new AgentDef("bci",        "Synapse", "BCI / EEG",     "#ce93d8"),
            new AgentDef("health",     "Pulse",   "Health",        "#f48fb1"),
            new AgentDef("comms",      "Echo",    "Comms",         "#fff176"),
            new AgentDef("photo",      "Lens",    "Photo Lab",     "#a5d6a7"),
            new AgentDef("news",       "Herald",  "News",          "#ef9a9a"),
            new AgentDef("linkedin",   "Nexus",   "Network",       "#90caf9"),
        };

        public static Color ZeroColor => Hex("#00e5ff");
        public static Color VColor    => Hex("#c792ea");

        public static Color Hex(string h)
        {
            ColorUtility.TryParseHtmlString(h, out var c);
            return c;
        }

        public static int IndexOf(string id)
        {
            for (int i = 0; i < All.Length; i++) if (All[i].id == id) return i;
            return -1;
        }

        // Piecewise hue gradient by side; v = vertical position 0 (top) .. 1 (bottom).
        // LEFT keeps a green/teal low band; RIGHT magenta->pink->red->orange->yellow.
        static readonly Vector2[] L = { new(0f, 222f), new(0.40f, 192f), new(0.70f, 158f), new(1f, 134f) };
        static readonly Vector2[] R = { new(0f, 305f), new(0.28f, 322f), new(0.52f, 352f), new(0.74f, 18f), new(1f, 58f) };

        /// <param name="side">0 = left (logic), 1 = right (creative)</param>
        public static float HueFor(int side, float v)
        {
            var st = side == 0 ? L : R;
            for (int i = 0; i < st.Length - 1; i++)
            {
                if (v <= st[i + 1].x)
                {
                    float t0 = st[i].x, t1 = st[i + 1].x, h0 = st[i].y, h1 = st[i + 1].y;
                    float f = (v - t0) / Mathf.Max(1e-4f, t1 - t0);
                    return h0 + (h1 - h0) * f;
                }
            }
            return st[st.Length - 1].y;
        }

        public static Color FromHue(float hueDeg, float s, float v)
        {
            float h = (((hueDeg % 360f) + 360f) % 360f) / 360f;
            return Color.HSVToRGB(h, s, v);
        }

        /// <summary>HDR-emissive version of a colour (intensity in stops) for bloom.</summary>
        public static Color Hdr(Color c, float intensity)
        {
            float f = Mathf.Pow(2f, intensity);
            return new Color(c.r * f, c.g * f, c.b * f, c.a);
        }

        // ── Warm vibrant palette (original theme: oranges / ambers / reds / magentas / golds) ──
        public static readonly Color[] SphereColor =
        {
            Hex("#ff7a18"), // orange
            Hex("#ffae00"), // amber
            Hex("#ffd000"), // gold
            Hex("#ff4d1a"), // red-orange
            Hex("#ff2d55"), // red
            Hex("#e60050"), // crimson
            Hex("#ff2db4"), // hot pink
            Hex("#ff5ec4"), // pink
            Hex("#ff6a00"), // deep orange
            Hex("#ff8c5a"), // peach
            Hex("#b6ff3c"), // lime accent
            Hex("#ffe23d"), // yellow
        };

        /// <summary>n unit directions spread ~evenly on a sphere (Fibonacci lattice).</summary>
        public static Vector3[] FibonacciAnchors(int n)
        {
            var pts = new Vector3[n];
            float ga = Mathf.PI * (3f - Mathf.Sqrt(5f)); // golden angle
            for (int i = 0; i < n; i++)
            {
                float y = 1f - (i / (float)(n - 1)) * 2f;
                float r = Mathf.Sqrt(Mathf.Max(0f, 1f - y * y));
                float th = ga * i;
                pts[i] = new Vector3(Mathf.Cos(th) * r, y, Mathf.Sin(th) * r);
            }
            return pts;
        }
    }
}
