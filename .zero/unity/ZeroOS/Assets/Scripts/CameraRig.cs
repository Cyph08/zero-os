using UnityEngine;
using UnityEngine.InputSystem;

namespace ZeroOS
{
    /// <summary>
    /// Drag to orbit, scroll to zoom, R / double-click to reset. Always frames the constellation
    /// centre (its target's world position) so the graph stays centred even if offset. Uses the
    /// new Input System (the project's active handler), so no legacy-Input dependency.
    /// </summary>
    public class CameraRig : MonoBehaviour
    {
        public Transform target;               // constellation centre
        public float distance = 16f;
        public float minDistance = 5f;
        public float maxDistance = 45f;
        public float orbitSpeed = 0.18f;
        public float zoomSpeed = 2.5f;
        public float smooth = 10f;

        float _yaw, _pitch = 8f, _yawT, _pitchT = 8f, _dist, _distT;
        Vector3 _center;
        float _lastClick = -1f;

        void Start()
        {
            _dist = _distT = distance;
            if (target != null) _center = target.position;
        }

        void LateUpdate()
        {
            if (target != null) _center = Vector3.Lerp(_center, target.position, 0.25f);

            var mouse = Mouse.current;
            var kb = Keyboard.current;
            if (mouse != null)
            {
                if (mouse.leftButton.isPressed)
                {
                    Vector2 d = mouse.delta.ReadValue();
                    _yawT += d.x * orbitSpeed;
                    _pitchT = Mathf.Clamp(_pitchT - d.y * orbitSpeed, -85f, 85f);
                }
                if (mouse.leftButton.wasPressedThisFrame)
                {
                    if (Time.unscaledTime - _lastClick < 0.3f) Reset();   // double-click
                    _lastClick = Time.unscaledTime;
                }
                float sc = mouse.scroll.ReadValue().y;
                if (Mathf.Abs(sc) > 0.01f) _distT = Mathf.Clamp(_distT - sc * 0.01f * zoomSpeed, minDistance, maxDistance);
            }
            if (kb != null && kb.rKey.wasPressedThisFrame) Reset();

            _yaw = Mathf.Lerp(_yaw, _yawT, Time.deltaTime * smooth);
            _pitch = Mathf.Lerp(_pitch, _pitchT, Time.deltaTime * smooth);
            _dist = Mathf.Lerp(_dist, _distT, Time.deltaTime * smooth);

            var rot = Quaternion.Euler(_pitch, _yaw, 0f);
            transform.position = _center + rot * new Vector3(0f, 0f, -_dist);
            transform.LookAt(_center);
        }

        void Reset() { _yawT = 0f; _pitchT = 8f; _distT = distance; }
    }
}
