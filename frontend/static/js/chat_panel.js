/**
 * ChildCareAI Admin Agent — Chat Panel JavaScript
 *
 * Manages the floating chat panel WebSocket connection,
 * message rendering, and user interactions.
 */

(function () {
    "use strict";

    // Configuration
    const WS_BASE_URL = window.location.protocol === "https:"
        ? `wss://${window.location.host}`
        : `ws://${window.location.host}`;

    // State
    let ws = null;
    let sessionId = generateSessionId();
    let isConnected = false;

    // DOM Elements
    const toggle = document.getElementById("chat-toggle");
    const panel = document.getElementById("chat-panel");
    const closeBtn = document.getElementById("chat-close");
    const messagesContainer = document.getElementById("chat-messages");
    const inputField = document.getElementById("chat-input");
    const sendBtn = document.getElementById("chat-send");
    const typingIndicator = document.getElementById("typing-indicator");

    // --- Initialization ---

    function init() {
        if (!toggle || !panel) return;

        toggle.addEventListener("click", togglePanel);
        closeBtn.addEventListener("click", closePanel);
        sendBtn.addEventListener("click", sendMessage);
        inputField.addEventListener("keydown", handleKeyDown);

        // Auto-connect when panel opens
    }

    // --- Panel Controls ---

    function togglePanel() {
        panel.classList.toggle("open");
        if (panel.classList.contains("open")) {
            connectWebSocket();
            inputField.focus();
        }
    }

    function closePanel() {
        panel.classList.remove("open");
    }

    // --- WebSocket Connection ---

    function connectWebSocket() {
        if (ws && ws.readyState === WebSocket.OPEN) return;

        ws = new WebSocket(`${WS_BASE_URL}/ws/chat/${sessionId}`);

        ws.onopen = function () {
            isConnected = true;
            console.log("[ChildCareAI] WebSocket connected");
        };

        ws.onmessage = function (event) {
            const data = JSON.parse(event.data);
            handleServerMessage(data);
        };

        ws.onclose = function () {
            isConnected = false;
            console.log("[ChildCareAI] WebSocket disconnected");
            // Auto-reconnect after 3 seconds
            setTimeout(function () {
                if (panel.classList.contains("open")) {
                    connectWebSocket();
                }
            }, 3000);
        };

        ws.onerror = function (error) {
            console.error("[ChildCareAI] WebSocket error:", error);
        };
    }

    // --- Message Handling ---

    function sendMessage() {
        const content = inputField.value.trim();
        if (!content || !isConnected) return;

        // Render user message
        appendMessage("user", content);
        inputField.value = "";

        // Show typing indicator
        showTyping(true);

        // Send via WebSocket
        ws.send(JSON.stringify({
            type: "message",
            content: content,
            session_id: sessionId,
        }));
    }

    function handleServerMessage(data) {
        switch (data.type) {
            case "chunk":
                // Streaming partial response
                appendOrUpdateAgentMessage(data.content);
                break;
            case "complete":
                // Final response
                showTyping(false);
                appendMessage("agent", data.content);
                break;
            case "ack":
                // Acknowledgment (development mode)
                showTyping(false);
                appendMessage("agent", data.content);
                break;
            case "tool_call":
                // Tool execution result
                appendToolResult(data.tool, data.result);
                break;
            case "approval_required":
                // Show approval banner
                showApprovalBanner(data.token, data.action);
                break;
            case "error":
                showTyping(false);
                appendMessage("agent", `⚠️ ${data.content || "An error occurred."}`);
                break;
            default:
                console.warn("[ChildCareAI] Unknown message type:", data.type);
        }
    }

    // --- DOM Manipulation ---

    function appendMessage(role, content) {
        const msgEl = document.createElement("div");
        msgEl.className = `chat-message ${role}`;
        msgEl.textContent = content;

        const timestamp = document.createElement("div");
        timestamp.className = "timestamp";
        timestamp.textContent = new Date().toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
        });
        msgEl.appendChild(timestamp);

        messagesContainer.appendChild(msgEl);
        scrollToBottom();
    }

    function appendOrUpdateAgentMessage(content) {
        // For streaming: update last agent message or create new one
        let lastAgent = messagesContainer.querySelector(".chat-message.agent:last-of-type");
        if (!lastAgent || lastAgent.dataset.complete === "true") {
            lastAgent = document.createElement("div");
            lastAgent.className = "chat-message agent";
            messagesContainer.appendChild(lastAgent);
        }
        lastAgent.textContent = content;
        scrollToBottom();
    }

    function appendToolResult(toolName, result) {
        const msgEl = document.createElement("div");
        msgEl.className = "chat-message agent";
        msgEl.innerHTML = `<strong>🔧 ${toolName}</strong><br><small>${JSON.stringify(result, null, 2)}</small>`;
        messagesContainer.appendChild(msgEl);
        scrollToBottom();
    }

    function showTyping(show) {
        if (typingIndicator) {
            typingIndicator.classList.toggle("active", show);
        }
    }

    function showApprovalBanner(token, action) {
        const banner = document.getElementById("approval-banner");
        if (banner) {
            banner.textContent = `⏳ Awaiting director approval: ${action}`;
            banner.classList.add("active");
        }
    }

    function scrollToBottom() {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    // --- Event Handlers ---

    function handleKeyDown(event) {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            sendMessage();
        }
    }

    // --- Utilities ---

    function generateSessionId() {
        return "sess_" + crypto.randomUUID().replace(/-/g, "").slice(0, 16);
    }

    // --- Bootstrap ---
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
