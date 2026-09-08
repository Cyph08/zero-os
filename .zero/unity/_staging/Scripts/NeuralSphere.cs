using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;

namespace ZeroOS
{
    /// <summary>
    /// Warm volumetric node-sphere with 8 atom-style crossing orbit rings, always-on gold
    /// connection-line web, 100 outer halo nodes linked to agents, and radiation particles.
    /// THINKING pulses lines + speeds orbits; SPEAKING highlights the active agent + breathes
    /// the sphere + bursts radiation. MeshRenderer-based (HDRP-safe).
    /// Drive with SetAudioLevel / SetActiveAgents / SetEmotion / SetPersona.
    /// </summary>
    public class NeuralSphere : MonoBehaviour
    {
        const int N = 12;

        [Header("Sphere")]
        public float sphereRadius  = 4.2f;
        public float outerRadius   = 6.8f;
        public int   nodeCount     = 900;
        public int   outerNodes    = 100;

        [Header("Look")]
        public float nodeSize      = 0.068f;
        public float hubSize       = 0.19f;
        public float outerSize     = 0.055f;
        public float nodeEmissive  = 2.8f;
        public float hubEmissive   = 4.2f;
        public float webIntensity  = 2.0f;

        [Header("Orbits")]
        public int   orbitCount       = 8;
        public float orbitRadius      = 5.2f;
        public float orbitSpeed       = 28f;   // degrees/sec
        public float orbitTravelSize  = 0.13f;

        [Header("Radiation")]
        public int radCount = 60;

        [Header("Motion")]
        public float spin = 3.5f;

        // ── internals ────────────────────────────────────────────────────────────
        Mesh _sphere;
        Transform _root;

        readonly Material[]     _nodeNormal = new Material[N];
        readonly Material[]     _nodeActive = new Material[N];
        readonly MeshRenderer[] _nodeR      = new MeshRenderer[N];
        readonly MeshRenderer[] _lineR      = new MeshRenderer[N];
        Material _webNormal, _webActive;

        readonly Vector3[] _hub  = new Vector3[N];
        readonly Color     _gold = new Color(1f, 0.82f, 0.5f);

        struct Orbit { public Transform traveler; public Quaternion tilt; public float phase; }
        Orbit[] _orbits;

        struct Rad { public Transform go; public int agent; public Vector3 dir; public float t; public float dur; }
        Rad[] _rads;

        Mesh _collabMesh; Material _collabMat;

        float        _audio, _energy, _time;
        Emotion      _emotion = Emotion.Idle;
        bool         _speaking, _thinking;
        readonly HashSet<int>  _active     = new();
        readonly List<int>     _activeList = new();

        // ── lifecycle ────────────────────────────────────────────────────────────
        void Start() { _sphere = MakeSphere(); Build(); }

        // ── public API ────────────────────────────────────────────────────────────
        public void SetAudioLevel(float v) => _audio = Mathf.Clamp01(v);
        public void SetEmotion(Emotion e)  => _emotion = e;
        public void SetPersona(Color c)    { }
        public void SetActiveAgents(IEnumerable<string> ids)
        {
            _active.Clear();
            if (ids != null)
                foreach (var id in ids) { int i = Agents.IndexOf(id); if (i >= 0) _active.Add(i); }
        }

        // ── build ─────────────────────────────────────────────────────────────────
        void Build()
        {
            _root = new GameObject("SphereRoot").transform;
            _root.SetParent(transform, false);
            var sh = Shader.Find("HDRP/Unlit");

            _webNormal = Emis(sh, _gold, webIntensity);
            _webActive = Emis(sh, _gold, webIntensity + 1.8f);
            _collabMat = Emis(sh, _gold, webIntensity + 2.5f);

            var anchors = Agents.FibonacciAnchors(N);
            for (int a = 0; a < N; a++) _hub[a] = anchors[a] * sphereRadius;

            // ── 900 volumetric nodes → nearest-agent bucket ──────────────────────
            var buckets = new List<Vector3>[N];
            for (int a = 0; a < N; a++) buckets[a] = new List<Vector3>();

            for (int i = 0; i < nodeCount; i++)
            {
                float r   = sphereRadius * Mathf.Pow(Random.value, 1f / 3f); // uniform volume fill
                Vector3 dir = Random.onUnitSphere;
                Vector3 p   = dir * r;
                int best = 0; float bd = -2f;
                for (int a = 0; a < N; a++) { float d = Vector3.Dot(dir, anchors[a]); if (d > bd) { bd = d; best = a; } }
                buckets[best].Add(p);
            }

            // ── 100 outer halo nodes → nearest agent ─────────────────────────────
            var outerByAgent = new List<Vector3>[N];
            for (int a = 0; a < N; a++) outerByAgent[a] = new List<Vector3>();
            var outerDirs = Agents.FibonacciAnchors(outerNodes);
            for (int o = 0; o < outerNodes; o++)
            {
                Vector3 dir = (outerDirs[o] + Random.insideUnitSphere * 0.10f).normalized;
                int best = 0; float bd = -2f;
                for (int a = 0; a < N; a++) { float d = Vector3.Dot(dir, anchors[a]); if (d > bd) { bd = d; best = a; } }
                outerByAgent[best].Add(dir * outerRadius * (0.88f + Random.value * 0.24f));
            }

            // ── per-agent: combined node mesh + gold web ──────────────────────────
            for (int a = 0; a < N; a++)
            {
                Color col = Agents.SphereColor[a];
                _nodeNormal[a] = Emis(sh, col, nodeEmissive);
                _nodeActive[a] = Emis(sh, col, nodeEmissive + 2.2f);

                // Node mesh: hub (bright/large) + bucket nodes + outer nodes
                var ci = new List<CombineInstance> { Inst(_hub[a], hubSize) };
                foreach (var p in buckets[a])      ci.Add(Inst(p, nodeSize));
                foreach (var p in outerByAgent[a]) ci.Add(Inst(p, outerSize));
                var nm = new Mesh { name = "N" + a, indexFormat = IndexFormat.UInt32 };
                nm.CombineMeshes(ci.ToArray(), true, true);
                var ngo = new GameObject("Agent_" + Agents.All[a].name);
                ngo.transform.SetParent(_root, false);
                ngo.AddComponent<MeshFilter>().sharedMesh = nm;
                var nmr = ngo.AddComponent<MeshRenderer>(); nmr.sharedMaterial = _nodeNormal[a]; NoShadow(nmr);
                _nodeR[a] = nmr;

                // Gold web: ~20% of bucket nodes → hub + cross edges + all outer → hub
                var lv = new List<Vector3>();
                int step = Mathf.Max(1, Mathf.RoundToInt(buckets[a].Count / 5f));
                for (int k = 0; k < buckets[a].Count; k += step)
                    { lv.Add(buckets[a][k]); lv.Add(_hub[a]); }
                for (int k = 0; k + step < buckets[a].Count; k += step * 2)
                    { lv.Add(buckets[a][k]); lv.Add(buckets[a][k + step]); }
                foreach (var p in outerByAgent[a]) { lv.Add(p); lv.Add(_hub[a]); }
                var lgo = new GameObject("Web_" + a);
                lgo.transform.SetParent(_root, false);
                lgo.AddComponent<MeshFilter>().sharedMesh = BuildLines(lv);
                var lmr = lgo.AddComponent<MeshRenderer>(); lmr.sharedMaterial = _webNormal; NoShadow(lmr);
                _lineR[a] = lmr;
            }

            // Hub-to-hub web: each hub → 3 nearest hubs (gold)
            var hv = new List<Vector3>();
            for (int a = 0; a < N; a++)
            {
                var d = new List<(float dist, int idx)>();
                for (int b = 0; b < N; b++) if (b != a) d.Add(((_hub[a] - _hub[b]).magnitude, b));
                d.Sort((x, y) => x.dist.CompareTo(y.dist));
                for (int m = 0; m < 3 && m < d.Count; m++)
                    if (a < d[m].idx) { hv.Add(_hub[a]); hv.Add(_hub[d[m].idx]); }
            }
            var hgo = new GameObject("HubWeb"); hgo.transform.SetParent(_root, false);
            hgo.AddComponent<MeshFilter>().sharedMesh = BuildLines(hv);
            var hmr = hgo.AddComponent<MeshRenderer>(); hmr.sharedMaterial = _webNormal; NoShadow(hmr);

            // Collab lines (dynamic, bright gold between active agents)
            _collabMesh = new Mesh { name = "Collab" }; _collabMesh.MarkDynamic();
            var cgo = new GameObject("Collab"); cgo.transform.SetParent(_root, false);
            cgo.AddComponent<MeshFilter>().sharedMesh = _collabMesh;
            var cmr = cgo.AddComponent<MeshRenderer>(); cmr.sharedMaterial = _collabMat; NoShadow(cmr);

            BuildOrbits(sh);
            BuildRadiation(sh);
        }

        void BuildOrbits(Shader sh)
        {
            _orbits = new Orbit[orbitCount];
            float[] tilts  = { 0f, 23.5f,  47f,  68f, 90f, 112f, 134f, 156f };
            float[] twists = { 0f,   35f,  70f, 105f, 22f,  55f,  88f, 122f };

            var orbitMat = Emis(sh, new Color(1f, 0.75f, 0.38f), 2.2f);   // warm amber ring

            for (int i = 0; i < orbitCount; i++)
            {
                var rot = Quaternion.Euler(tilts[i % tilts.Length], twists[i % twists.Length], 0f);

                // Ring mesh (line loop, 64 segments)
                int seg = 64;
                var rv = new Vector3[seg];
                var ri = new int[seg * 2];
                for (int s = 0; s < seg; s++)
                {
                    float ang = s * Mathf.PI * 2f / seg;
                    rv[s] = rot * new Vector3(Mathf.Cos(ang) * orbitRadius, Mathf.Sin(ang) * orbitRadius, 0f);
                    ri[s * 2] = s; ri[s * 2 + 1] = (s + 1) % seg;
                }
                var rm = new Mesh { indexFormat = IndexFormat.UInt32 };
                rm.vertices = rv; rm.SetIndices(ri, MeshTopology.Lines, 0);
                rm.bounds = new Bounds(Vector3.zero, Vector3.one * orbitRadius * 2.2f);

                var rgo = new GameObject("Orbit" + i); rgo.transform.SetParent(_root, false);
                rgo.AddComponent<MeshFilter>().sharedMesh = rm;
                var rmr = rgo.AddComponent<MeshRenderer>(); rmr.sharedMaterial = orbitMat; NoShadow(rmr);

                // Traveling node along the ring
                var tgo = GameObject.CreatePrimitive(PrimitiveType.Sphere);
                Destroy(tgo.GetComponent<Collider>());
                tgo.name = "Traveler" + i; tgo.transform.SetParent(_root, false);
                tgo.transform.localScale = Vector3.one * orbitTravelSize;
                var tmr = tgo.GetComponent<MeshRenderer>();
                tmr.sharedMaterial = Emis(sh, new Color(1f, 0.90f, 0.60f), hubEmissive); NoShadow(tmr);

                _orbits[i] = new Orbit { traveler = tgo.transform, tilt = rot, phase = i * 360f / orbitCount };
            }
        }

        void BuildRadiation(Shader sh)
        {
            _rads = new Rad[radCount];
            var radMat = Emis(sh, new Color(1f, 0.70f, 0.30f), 3.2f);
            for (int i = 0; i < radCount; i++)
            {
                var go = GameObject.CreatePrimitive(PrimitiveType.Sphere);
                Destroy(go.GetComponent<Collider>());
                go.name = "Rad" + i; go.transform.SetParent(_root, false);
                go.transform.localScale = Vector3.one * 0.07f;
                var mr = go.GetComponent<MeshRenderer>(); mr.sharedMaterial = radMat; NoShadow(mr);
                go.SetActive(false);
                _rads[i] = new Rad { go = go.transform, agent = Random.Range(0, N), dir = Random.onUnitSphere, t = 1f, dur = 1f };
            }
        }

        // ── per-frame ──────────────────────────────────────────────────────────────
        void Update()
        {
            _time += Time.deltaTime;

            float target = _emotion switch
            {
                Emotion.Speaking  => 0.65f,
                Emotion.Thinking  => 0.45f,
                Emotion.Listening => 0.25f,
                _                 => 0.10f,
            };
            if (_audio > 0.01f) target = Mathf.Max(target, _audio);
            _energy = Mathf.Lerp(_energy, target, 0.12f);

            _speaking = _emotion == Emotion.Speaking;
            _thinking = _emotion == Emotion.Thinking;
            _activeList.Clear(); _activeList.AddRange(_active);

            // Sphere rotation + scale breathe
            _root.localRotation = Quaternion.Euler(
                _time * spin * 0.18f,
                _time * spin * (1f + _energy * 1.8f),
                _time * spin * 0.07f);
            float wide = 1f + _audio * (_speaking ? 0.20f : 0.04f);
            float tall = 1f + _audio * (_speaking ? 0.10f : 0.02f);
            _root.localScale = new Vector3(wide, tall, wide);

            // Gold web pulse (faster/brighter while thinking)
            float pulse = _thinking ? 0.5f + 0.5f * Mathf.Abs(Mathf.Sin(_time * 8f)) : 1f;
            if (_webNormal != null)
                _webNormal.SetColor("_EmissiveColor", Agents.Hdr(_gold, webIntensity + _energy * 0.7f) * pulse);
            if (_webActive != null)
                _webActive.SetColor("_EmissiveColor", Agents.Hdr(_gold, webIntensity + 2.0f) * pulse);

            // Per-agent highlight
            for (int a = 0; a < N; a++)
            {
                bool act = _active.Contains(a);
                var wantNode = (_speaking && act) ? _nodeActive[a] : _nodeNormal[a];
                if (_nodeR[a] != null && _nodeR[a].sharedMaterial != wantNode)
                    _nodeR[a].sharedMaterial = wantNode;
                if (_lineR[a] != null)
                {
                    var wantLine = act ? _webActive : _webNormal;
                    if (_lineR[a].sharedMaterial != wantLine) _lineR[a].sharedMaterial = wantLine;
                }
            }

            UpdateOrbits();
            UpdateRadiation();
            UpdateCollab();
        }

        void UpdateOrbits()
        {
            float spd = orbitSpeed * (1f + _energy * 1.5f) * Time.deltaTime;
            for (int i = 0; i < _orbits.Length; i++)
            {
                _orbits[i].phase += spd * (i % 2 == 0 ? 1f : -1f);
                float ang = _orbits[i].phase * Mathf.Deg2Rad;
                _orbits[i].traveler.localPosition = _orbits[i].tilt *
                    new Vector3(Mathf.Cos(ang) * orbitRadius, Mathf.Sin(ang) * orbitRadius, 0f);
            }
        }

        void UpdateRadiation()
        {
            float spawnChance = _speaking ? 0.70f : (_energy > 0.3f ? 0.25f : 0.06f);
            for (int i = 0; i < _rads.Length; i++)
            {
                ref Rad r = ref _rads[i];
                if (!r.go.gameObject.activeSelf)
                {
                    if (Random.value < spawnChance * Time.deltaTime * 5f)
                    {
                        r.agent = _activeList.Count > 0
                            ? _activeList[Random.Range(0, _activeList.Count)]
                            : Random.Range(0, N);
                        r.dir = (_hub[r.agent].normalized + Random.insideUnitSphere * 0.35f).normalized;
                        r.t   = 0f;
                        r.dur = 0.7f + Random.value * 1.1f;
                        r.go.gameObject.SetActive(true);
                    }
                    continue;
                }
                r.t += Time.deltaTime / r.dur;
                if (r.t >= 1f) { r.go.gameObject.SetActive(false); continue; }
                float reach = Mathf.Sin(r.t * Mathf.PI);
                r.go.localPosition = _hub[r.agent] + r.dir * (outerRadius * 0.65f * reach);
                r.go.localScale    = Vector3.one * (0.07f * Mathf.Max(0.15f, reach));
            }
        }

        void UpdateCollab()
        {
            if (_activeList.Count < 2) { _collabMesh.Clear(); return; }
            int pairs = _activeList.Count * (_activeList.Count - 1) / 2;
            var v   = new Vector3[pairs * 2];
            var idx = new int[pairs * 2];
            int vi  = 0;
            for (int i = 0; i < _activeList.Count; i++)
                for (int j = i + 1; j < _activeList.Count; j++)
                {
                    v[vi] = _hub[_activeList[i]]; v[vi + 1] = _hub[_activeList[j]];
                    idx[vi] = vi; idx[vi + 1] = vi + 1; vi += 2;
                }
            _collabMesh.Clear();
            _collabMesh.vertices = v;
            _collabMesh.SetIndices(idx, MeshTopology.Lines, 0);
            _collabMesh.bounds = new Bounds(Vector3.zero, Vector3.one * outerRadius * 2.5f);
        }

        // ── helpers ──────────────────────────────────────────────────────────────
        CombineInstance Inst(Vector3 p, float s) =>
            new() { mesh = _sphere, transform = Matrix4x4.TRS(p, Quaternion.identity, Vector3.one * s) };

        static Mesh BuildLines(List<Vector3> verts)
        {
            var m   = new Mesh { indexFormat = IndexFormat.UInt32 };
            var v   = verts.ToArray();
            var idx = new int[v.Length];
            for (int i = 0; i < v.Length; i++) idx[i] = i;
            m.vertices = v;
            m.SetIndices(idx, MeshTopology.Lines, 0);
            m.bounds = new Bounds(Vector3.zero, Vector3.one * 100f);
            return m;
        }

        static Material Emis(Shader sh, Color c, float inten)
        {
            var m = new Material(sh);
            m.SetColor("_UnlitColor",    Color.black);
            m.SetColor("_EmissiveColor", Agents.Hdr(c, inten));
            return m;
        }

        static void NoShadow(MeshRenderer mr)
        {
            mr.shadowCastingMode = ShadowCastingMode.Off;
            mr.receiveShadows    = false;
        }

        static Mesh MakeSphere()
        {
            var go = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            var m  = go.GetComponent<MeshFilter>().sharedMesh;
            Destroy(go);
            return m;
        }
    }
}
