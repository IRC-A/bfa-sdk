import { useAppState } from "./StateContext";
import AppLayout from "./Layout";
import ChatBox from "./components/ChatBox";
import PromptSuggestions from "./components/PromptSuggestions";
import { GATEWAY_URL } from "./config";

export default function ChatPage() {
    const { messages, setMessages, loading, setLoading, updateState, state } =
        useAppState();

    async function sendMessage(message) {
        if (!message.trim()) return;

        const userMessage = {
            id: crypto.randomUUID(),
            role: "user",
            content: message,
        };
        setMessages((prev) => [...prev, userMessage]);
        setLoading(true);

        // Generamos un session_id dinámico o usamos uno existente
        const session_id = state.session_id || crypto.randomUUID();
        // Guardamos el session_id en el estado si no existía
        if (!state.session_id) {
            updateState({ session_id });
        }

        try {
            // Invoke the routed microservice via BFA Gateway
            const response = await fetch(`${GATEWAY_URL}/invoke?query=${encodeURIComponent(message)}`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    jsonrpc: "2.0",
                    method: "agent.execute",
                    params: {
                        user_input: {
                            text: message
                        }
                    },
                    id: 1
                }),
            });

            if (!response.ok) {
                throw new Error("Failed to invoke BFA Gateway");
            }

            const data = await response.json();
            
            // Extract response text from A2A JSON-RPC format
            let textResponse = "";
            if (data.error) {
                textResponse = `⚠️ **Agent Error (${data.error.code}):** ${data.error.message}`;
            } else {
                textResponse = data?.result?.output?.text || "No structured response received from agent.";
            }

            const assistantId = crypto.randomUUID();

            setMessages((prev) => [
                ...prev,
                {
                    id: assistantId,
                    role: "assistant",
                    content: textResponse,
                },
            ]);

            // Update shared state responses for telemetry processor
            updateState({
                responses: [textResponse]
            });

        } catch (err) {
            console.error("Error sending message:", err);
            setMessages((prev) => [
                ...prev,
                {
                    id: crypto.randomUUID(),
                    role: "assistant",
                    content: "Connection error with BFA Gateway. Please verify that the Gateway server is online.",
                },
            ]);
        } finally {
            setLoading(false);
        }
    }

    return (
        <AppLayout>
        {messages.length === 0 ? (
            <PromptSuggestions onSelect={sendMessage} />
        ) : (
            <ChatBox
            messages={messages}
            setMessages={setMessages}
            onSend={sendMessage}
            loading={loading}
            />
        )}
        </AppLayout>
    );
}