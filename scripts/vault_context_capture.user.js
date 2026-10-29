// ==UserScript==
// @name         Vault Context Capture
// @namespace    vault-context-mcp
// @version      0.1.0
// @description  Capture selected LLM chat text into vault-context-mcp through the local capture server.
// @match        https://chatgpt.com/*
// @match        https://chat.openai.com/*
// @match        https://gemini.google.com/*
// @match        https://claude.ai/*
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// @connect      localhost
// ==/UserScript==

(function () {
  "use strict";

  const ENDPOINT = "http://127.0.0.1:8765/capture";
  const MAX_TRANSCRIPT_CHARS = 190000;
  const BUTTON_ID = "vault-context-capture-button";

  function inferSource(hostname) {
    const host = hostname.toLowerCase();
    if (host.includes("chatgpt") || host.includes("openai")) {
      return "chatgpt";
    }
    if (host.includes("gemini.google")) {
      return "gemini";
    }
    if (host.includes("claude.ai")) {
      return "claude";
    }
    return "other";
  }

  function selectedOrVisibleText() {
    const selected = window.getSelection().toString().trim();
    if (selected) {
      return selected;
    }
    if (!window.confirm("No text is selected. Capture the visible page text instead?")) {
      return "";
    }
    return document.body.innerText.trim();
  }

  function cleanDefaultTitle() {
    return (document.title || "LLM session")
      .replace(/\s+[|-]\s+ChatGPT$/i, "")
      .replace(/\s+[|-]\s+Claude$/i, "")
      .replace(/\s+[|-]\s+Gemini$/i, "")
      .trim();
  }

  function requestCapturePayload() {
    let transcript = selectedOrVisibleText();
    if (!transcript) {
      return null;
    }
    if (transcript.length > MAX_TRANSCRIPT_CHARS) {
      const ok = window.confirm(
        "This capture is very large. Truncate it to the local capture limit?"
      );
      if (!ok) {
        return null;
      }
      transcript = transcript.slice(0, MAX_TRANSCRIPT_CHARS);
    }

    const source = inferSource(window.location.hostname);
    const title =
      window.prompt("Vault capture title", cleanDefaultTitle() || "LLM session") ||
      "LLM session";
    const project = window.prompt("Project name (optional)", "") || null;
    const summary = window.prompt("One-sentence summary (optional)", "") || null;

    return {
      source,
      title,
      transcript,
      origin: window.location.href,
      project,
      summary,
      key_takeaways: [],
      decisions: [],
      open_questions: [],
      next_actions: []
    };
  }

  function postJson(payload) {
    const body = JSON.stringify(payload);
    return new Promise((resolve, reject) => {
      if (typeof GM_xmlhttpRequest === "function") {
        GM_xmlhttpRequest({
          method: "POST",
          url: ENDPOINT,
          headers: { "Content-Type": "application/json" },
          data: body,
          onload: (response) => {
            if (response.status >= 200 && response.status < 300) {
              resolve(JSON.parse(response.responseText));
            } else {
              reject(new Error(response.responseText || `HTTP ${response.status}`));
            }
          },
          onerror: () => reject(new Error("Could not reach local capture server"))
        });
        return;
      }

      fetch(ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body
      })
        .then(async (response) => {
          const text = await response.text();
          if (!response.ok) {
            throw new Error(text || `HTTP ${response.status}`);
          }
          return JSON.parse(text);
        })
        .then(resolve)
        .catch(reject);
    });
  }

  async function capture() {
    const payload = requestCapturePayload();
    if (!payload) {
      return;
    }
    const button = document.getElementById(BUTTON_ID);
    if (button) {
      button.textContent = "Logging...";
      button.disabled = true;
    }
    try {
      const result = await postJson(payload);
      window.alert(`Logged to vault:\n${result.path}`);
    } catch (error) {
      window.alert(
        `Vault capture failed.\n\n${error.message}\n\nCheck that vault-context serve-capture is running.`
      );
    } finally {
      if (button) {
        button.textContent = "Log to Vault";
        button.disabled = false;
      }
    }
  }

  function addButton() {
    if (document.getElementById(BUTTON_ID)) {
      return;
    }
    const button = document.createElement("button");
    button.id = BUTTON_ID;
    button.type = "button";
    button.textContent = "Log to Vault";
    button.title = "Capture selected chat text into your Obsidian vault";
    Object.assign(button.style, {
      position: "fixed",
      right: "18px",
      bottom: "18px",
      zIndex: "2147483647",
      padding: "10px 12px",
      borderRadius: "8px",
      border: "1px solid rgba(120, 120, 120, 0.45)",
      background: "#111827",
      color: "#ffffff",
      font: "13px system-ui, -apple-system, BlinkMacSystemFont, sans-serif",
      boxShadow: "0 8px 24px rgba(0, 0, 0, 0.22)",
      cursor: "pointer"
    });
    button.addEventListener("click", capture);
    document.body.appendChild(button);
  }

  function installKeyboardShortcut() {
    window.addEventListener("keydown", (event) => {
      if ((event.metaKey || event.ctrlKey) && event.shiftKey && event.key.toLowerCase() === "l") {
        event.preventDefault();
        capture();
      }
    });
  }

  addButton();
  installKeyboardShortcut();
})();
