using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;

namespace ZeroOS
{
    /// <summary>
    /// One-component scene setup (no HDRP volume/camera GUI needed): black camera with TAA + a
    /// CameraRig (drag-orbit / scroll-zoom / reset), a Global Volume (Bloom + ACES + Fixed Exposure),
    /// and a visible starfield + a few faint galaxies. Drop on the ZeroOS object (with NeuralSphere).
    /// </summary>
    [DefaultExecutionOrder(-100)]
    public class SceneBootstrap : MonoBehaviour
    {
        public float fieldOfView = 55f;
        public float cameraDistance = 16f;

        [Header("Post")]
        public float bloomIntensity = 0.6f;
        public float bloomScatter = 0.75f;
        [Tooltip("HDRP Fixed Exposure (EV100). LOWER = brighter image. ~4 suits a dark emissive scene.")]
        public float fixedExposure = 4f;

        [Header("Space")]
        public int starCount = 600;
        public float starFieldRadius = 70f;
        public int galaxyCount = 4;

        Mesh _star;

        void Awake()
        {
            _star = MakeSphere();
            SetupCamera();
            SetupVolume();
            BuildStars();
            BuildGalaxies();
        }

        void SetupCamera()
        {
            var cam = Camera.main;
            if (cam == null)
            {
                var go = new GameObject("Main Camera") { tag = "MainCamera" };
                cam = go.AddComponent<Camera>();
            }
            cam.fieldOfView = fieldOfView;

            var hd = cam.GetComponent<HDAdditionalCameraData>();
            if (hd == null) hd = cam.gameObject.AddComponent<HDAdditionalCameraData>();
            hd.clearColorMode = HDAdditionalCameraData.ClearColorMode.Color;     // pure black bg
            hd.backgroundColorHDR = Color.black;
            hd.volumeLayerMask = ~0;
            hd.antialiasing = HDAdditionalCameraData.AntialiasingMode.TemporalAntialiasing;  // crisp thin lines

            if (cam.GetComponent<AudioListener>() == null) cam.gameObject.AddComponent<AudioListener>();

            var rig = cam.GetComponent<CameraRig>();
            if (rig == null) rig = cam.gameObject.AddComponent<CameraRig>();
            rig.target = transform;             // constellation centre
            rig.distance = cameraDistance;
        }

        void SetupVolume()
        {
            var go = new GameObject("ZeroVolume");
            var vol = go.AddComponent<Volume>();
            vol.isGlobal = true;
            vol.priority = 100f;

            var profile = ScriptableObject.CreateInstance<VolumeProfile>();
            vol.profile = profile;

            var bloom = profile.Add<Bloom>(true);
            bloom.intensity.Override(bloomIntensity);
            bloom.scatter.Override(bloomScatter);

            var tone = profile.Add<Tonemapping>(true);
            tone.mode.Override(TonemappingMode.ACES);

            var exp = profile.Add<Exposure>(true);
            exp.mode.Override(ExposureMode.Fixed);
            exp.fixedExposure.Override(fixedExposure);
        }

        void BuildStars()
        {
            var ci = new List<(Vector3 p, float s)>(starCount);
            for (int i = 0; i < starCount; i++)
            {
                Vector3 p = Random.onUnitSphere * starFieldRadius * (0.8f + Random.value * 0.2f);
                ci.Add((p, 0.10f + Random.value * 0.16f));
            }
            var go = new GameObject("Starfield");
            go.AddComponent<MeshFilter>().sharedMesh = Combine(ci);
            var mr = go.AddComponent<MeshRenderer>();
            mr.sharedMaterial = Emis(new Color(0.85f, 0.86f, 0.95f), 0.9f);   // dim, visible
            NoShadow(mr);
        }

        void BuildGalaxies()
        {
            Color[] cols = { new(0.55f, 0.4f, 0.85f), new(0.35f, 0.55f, 0.85f), new(0.85f, 0.45f, 0.65f), new(0.45f, 0.75f, 0.7f) };
            for (int g = 0; g < galaxyCount; g++)
            {
                var ci = new List<(Vector3 p, float s)>();
                for (int i = 0; i < 70; i++)
                {
                    float rr = Mathf.Pow(Random.value, 0.6f);
                    float ang = Random.value * Mathf.PI * 2f + rr * 6f;
                    float rad = rr * 4f;
                    ci.Add((new Vector3(Mathf.Cos(ang) * rad, (Random.value - 0.5f) * 0.6f, Mathf.Sin(ang) * rad), 0.16f));
                }
                var go = new GameObject("Galaxy_" + g);
                go.transform.position = Random.onUnitSphere * (starFieldRadius * 0.7f);
                go.transform.rotation = Random.rotation;
                go.AddComponent<MeshFilter>().sharedMesh = Combine(ci);
                var mr = go.AddComponent<MeshRenderer>();
                mr.sharedMaterial = Emis(cols[g % cols.Length], 1.0f);
                NoShadow(mr);
            }
        }

        // ── helpers ──────────────────────────────────────────────────────────────
        Mesh Combine(List<(Vector3 p, float s)> items)
        {
            var ci = new CombineInstance[items.Count];
            for (int i = 0; i < items.Count; i++)
                ci[i] = new CombineInstance { mesh = _star, transform = Matrix4x4.TRS(items[i].p, Quaternion.identity, Vector3.one * items[i].s) };
            var m = new Mesh { name = "Stars", indexFormat = IndexFormat.UInt32 };
            m.CombineMeshes(ci, true, true);
            return m;
        }

        static Material Emis(Color c, float inten)
        {
            var m = new Material(Shader.Find("HDRP/Unlit"));
            m.SetColor("_UnlitColor", Color.black);
            m.SetColor("_EmissiveColor", Agents.Hdr(c, inten));
            return m;
        }

        static void NoShadow(MeshRenderer mr) { mr.shadowCastingMode = ShadowCastingMode.Off; mr.receiveShadows = false; }

        static Mesh MakeSphere()
        {
            var go = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            var m = go.GetComponent<MeshFilter>().sharedMesh;
            Destroy(go);
            return m;
        }
    }
}
