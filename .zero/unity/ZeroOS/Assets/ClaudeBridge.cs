using System.Text;
using UnityEngine;
using UnityEngine.Networking;
using System.Collections;

public class ClaudeBridge : MonoBehaviour
{
    // NEVER hardcode the key here. Unity serialises public fields into the .unity
    // scene file, so a key typed here ends up committed twice (script + scene).
    // Set ANTHROPIC_API_KEY in the environment instead; Awake() reads it at runtime.
    [HideInInspector] public string apiKey = "";

    void Awake()
    {
        if (string.IsNullOrEmpty(apiKey))
        {
            apiKey = System.Environment.GetEnvironmentVariable("ANTHROPIC_API_KEY") ?? "";
        }
        if (string.IsNullOrEmpty(apiKey))
        {
            Debug.LogWarning("[ClaudeBridge] ANTHROPIC_API_KEY is not set — calls will fail.");
        }
    }

    public void SendToClaude(string prompt)
    {
        StartCoroutine(CallClaude(prompt));
    }

    IEnumerator CallClaude(string prompt)
    {
        string json = "{\"model\":\"claude-3-5-sonnet-20241022\",\"max_tokens\":500,\"messages\":[{\"role\":\"user\",\"content\":\"" + prompt + "\"}]}";

        var request = new UnityWebRequest("https://api.anthropic.com/v1/messages", "POST");
        byte[] bodyRaw = Encoding.UTF8.GetBytes(json);
        request.uploadHandler = new UploadHandlerRaw(bodyRaw);
        request.downloadHandler = new DownloadHandlerBuffer();

        request.SetRequestHeader("content-type", "application/json");
        request.SetRequestHeader("x-api-key", apiKey);
        request.SetRequestHeader("anthropic-version", "2023-06-01");

        yield return request.SendWebRequest();

        Debug.Log(request.downloadHandler.text);
    }
}